import os
from typing import List, Optional, Dict

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_core.messages import BaseMessage, ToolMessage, HumanMessage, ChatMessage
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings, ChatNVIDIA
from langgraph.graph import MessageGraph, END
from langgraph.graph.graph import CompiledGraph
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
from langchain_community.vectorstores import SurrealDBStore
from langchain_community.tools import DuckDuckGoSearchRun
from langchain_core.pydantic_v1 import BaseModel, Field
from tool_calling_model import create_tool_calling_model
import logging

load_dotenv()

logger = logging.getLogger(__name__)

nvidia_functions = create_tool_calling_model(ChatNVIDIA, "chat_nvidia_functions")

_nvidia_embed_model = (os.environ.get("NVIDIA_EMBEDDINGS_MODEL")
                       if "NVIDIA_EMBEDDINGS_MODEL" in os.environ
                       else "NV-Embed-QA")
_nvidia_vllm_model = (os.environ["NVIDIA_VLLM_MODEL"]
                      if "NVIDIA_VLLM_MODEL" in os.environ
                      else "microsoft/phi-3-vision-128k-instruct")
_nvidia_llm_model = (os.environ["NVIDIA_LLM_MODEL"]
                     if "NVIDIA_LLM_MODEL" in os.environ
                     else "meta/llama3-8b-instruct")

_vllm = ChatNVIDIA(model=_nvidia_vllm_model)
_llm = nvidia_functions(model=_nvidia_llm_model)
_nvidia_embed = NVIDIAEmbeddings(model=_nvidia_embed_model)
_sdb = SurrealDBStore(embedding_function=_nvidia_embed)


def _strip_content(content: str) -> str:
    return " ".join([line.strip() for line in content.split("\n")])


def _format_documents_for_query(docs: List[Document]) -> str:
    return "\n\n".join([f"document id: {doc.metadata["id"]}\n"
                        f"outfit description: {_strip_content(doc.page_content)}" for doc in docs])


class ListOfDocumentIds(BaseModel):
    """
    List of Document Ids
    Document id must have a prefix "documents:"
    """
    document_ids: Optional[List[str]] = Field(description="List of document ids")


@tool
async def outfit_recommender(request: str, context: Optional[str]) -> List[str]:
    """
    Outfit retriever tool takes an outfit search query and returns a list of outfits from the library
    of outfits. The request must include specifics like colors or style or occasion or venue.
    There may be some additional context that may be included request such as colors, styles, etc.
    The request must start with phrase "Show me".
    """
    logger.info(f"Outfit recommender request: {request}, context: {context}")
    if context is not None and len(context) > 0:
        prompt = PromptTemplate.from_examples(
            prefix="You are a user request pre-processor. Review user's original request and the provided context. """
                   "Rephrase the original request with any additional information from the context. "
                   "If no context is provided, then the rephrased request is the same as the original request.\n\n"
                   "See examples below:\n",
            examples=[
                "Example #1\n"
                "Context: \n"
                "Original Request: What is the capital of France?\n"
                "Rephrased Request: What is the capital of France?",
                "Example #2\n"
                "Context: Alice has a brother, named Bob.\n"
                "Original Request: What is Alice's brother's age?\n"
                "Rephrased Request: How old is Bob?",
                "Example #3\n"
                "Context: You put the bowl on the table.\n"
                "Original Request: You put cereal in it.\n"
                "Rephrased Request: You put cereal in the bowl on the table.",
                "Example #4\n"
                "Context: I have a red jacket.\n"
                "Original Request: I need matching shoes.\n"
                "Rephrased Request: I need matching shoes for my red jacket.",
            ],
            suffix="End of examples\n\n"
                   "Rephrase the below request\n\n"
                   "Context: {context}\n"
                   "Original Request: {request}\n"
                   "Rephrased Request: ",
            input_variables=["request", "context"]
        )
        chain = prompt | _llm
        response = chain.invoke({"request": request, "context": context})
        new_request = response.content
    else:
        new_request = request

    logger.info(f"Outfit recommender pre-processor response: {new_request}")

    retrieval_prompt = PromptTemplate.from_template("""
        Review the outfit descriptions below and find all that match the user's request.
        Return all document ids for the matching outfits.
        Document Ids must always begin with "documents:" prefix.
        Only return document ids.


        ** Outfit descriptions **
        {documents}

        ** User Request **
        {request}

        ** Matching Document IDs **
    """)

    await _sdb.initialize()
    retriever = _sdb.as_retriever()

    async def get_image_urls(doc_ids: ListOfDocumentIds) -> List[str]:
        documents = [await _sdb.sdb.select(doc_id) for doc_id in doc_ids.document_ids]
        return [doc["metadata"]["image_url"] for doc in documents]

    retrieval_chain = (
            {
                "documents": retriever | _format_documents_for_query,
                "request": RunnablePassthrough()
            } | retrieval_prompt | _llm.with_structured_output(ListOfDocumentIds) |
            RunnableLambda(get_image_urls)
    )

    try:
        results = await retrieval_chain.ainvoke(new_request)
        logger.info(f"Outfit recommender found {len(results)} matches")
    except Exception as e:
        logger.exception(e)
        results = ["error: Error retrieving outfit"]
    # return [result.metadata["image_url"] for result in results]
    return results


_tools = [DuckDuckGoSearchRun(max_results=5), outfit_recommender]
_llm_with_tools = _llm.bind_tools(_tools)
_tool_node = ToolNode(_tools)


async def process_image(filename: str, image_url: str):
    class Outfit(BaseModel):
        detailed_description: str = Field(description="A very detailed description of the picture")
        outfit_description: str = Field(description="A very detailed description of the outfit of the primary "
                                                    "subject. Include color of the outfit, style of the outfit, "
                                                    "and any additional identifying detail that can be helpful when "
                                                    "looking up this outfit.")
        outfit_type: str = Field(
            description="Type of outfit. example: shirt, trousers, blouse, jacket, shorts, skirt, etc")
        colors: List[str] = Field(description="List of all colors of the outfit")
        weather: str = Field(description="Weather conditions suitable for the outfit")

    def get_image_prompt(_image_url: str) -> List[BaseMessage]:
        return [HumanMessage(
            content=[
                {
                    "type": "text", "text": "You are an expert fashion classifier. Your task is to review the "
                                            "provided image and identify different characteristics about the outfits, "
                                            "such as color, style, pattern etc. You must also identify whether the "
                                            "outfit is formal, casual, etc, and what weather it is most suitable for. "
                                            "Focus only on the outfit and ignore everything else in the image, "
                                            "like the location, furniture, etc. Provide as much detail as possible."
                },
                {
                    "type": "image_url", "image_url": _image_url
                },
            ]
        )]

    def get_message_content(msg: ChatMessage) -> str:
        if isinstance(msg.content, str):
            return msg.content
        else:
            return msg.content[0]["text"]

    outfit_output_llm = _llm.with_structured_output(Outfit, include_raw=False)
    nv_fc_chain = RunnableLambda(get_image_prompt) | _vllm | RunnableLambda(get_message_content) | outfit_output_llm

    try:
        result = await nv_fc_chain.ainvoke(image_url)
        print(result)
        metadata = {
            "file": filename,
            "detailed_description": result.detailed_description,
            "outfit_description": result.outfit_description,
            "colors": result.colors,
            "outfit_type": result.outfit_type,
            "weather": result.weather,
            "image_url": image_url
        }
        page_content = f"""{result.outfit_description}

        Outfit colors: {", ".join(result.colors)}

        Outfit type: {result.outfit_type}

        Suitable for {result.weather} weather.
        """
        document = Document(page_content=page_content, metadata=metadata)
        await _sdb.initialize()
        ids = await _sdb.aadd_documents([document])
        logger.info(f"Outfit uploaded: {ids}")
    except Exception as e:
        logger.error(e)


def _oracle_node(messages: List[BaseMessage]) -> BaseMessage:
    logger.info("Oracle node")
    request = messages[-1]
    context = messages[:-1] if len(messages) > 1 else []
    prompt = PromptTemplate.from_template("""Review the request and answer it based on the context provided. 

    Request:
    {request}

    Context:
    {context}

    Response:
    """)
    chain = prompt | _llm_with_tools
    response = chain.invoke({"request": request.content, "context": context})
    logger.info(f"Oracle node response: {response.content}")
    return response


def _summarize_node(messages: List[BaseMessage]) -> Optional[BaseMessage]:
    logger.info("Summarize node")
    last_message = messages[-1]
    if not isinstance(last_message, ToolMessage) or (
            last_message.content[0] == '[' and last_message.content[-1] == ']'):
        return None
    request = [message for message in messages if isinstance(message, HumanMessage)][-1]
    prompt = PromptTemplate.from_template("""Review the request and provide a short one line response in simple 
    language based on the context. 

    Request:
    {request}

    Context:
    {context}

    Response:
    """)
    chain = prompt | _llm
    response = chain.invoke({"request": request.content, "context": last_message.content})
    logger.info(f"Summarize node response: {response.content}")
    return response


class Graph:

    def __init__(self):
        builder = MessageGraph()
        builder.add_node("oracle_node", _oracle_node)
        builder.add_node("tool_node", _tool_node)
        builder.add_node("summarize_node", _summarize_node)
        builder.add_edge("oracle_node", "tool_node")
        builder.add_edge("tool_node", "summarize_node")
        builder.add_edge("summarize_node", END)
        builder.set_entry_point("oracle_node")
        self.graph = builder.compile()

    def get_graph(self) -> CompiledGraph:
        return self.graph
