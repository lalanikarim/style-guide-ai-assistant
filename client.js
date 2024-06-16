let state = {
    pc:null,
    dc:null,
    stream:null,
}

let connectionStatus = document.querySelector("span#connectionStatus")
let wave = document.querySelector("div.wave")
let processing = document.querySelector("div.processing")
let messagesContainer =  document.querySelector("div#messagesContainer")
let chatNameContainer = document.querySelector("div.chat-container .user-bar .name")
let powerButton =  document.querySelector("button#power")
let presetsSelect = document.querySelector("select#presets")
let modelsSelect = document.querySelector("select#models")
let startRecordDiv = document.querySelector("div.circle.start")
let stopRecordDiv = document.querySelector("div.circle.stop")
let waitRecordDiv = document.querySelector("div.circle.wait")
let cameraImg = document.querySelector("div.photo i")
let fileInput = document.querySelector("div.file input[type=file]")

function getcconnectionstatus() {
    let status = "closed"
    if (state.pc) {
        status = state.pc.connectionState
    }
    connectionStatus.textContent = status
}

function negotiate() {
    //pc.addTransceiver('audio', { direction: 'sendrecv' });
    return state.pc.createOffer().then((offer) => {
        return state.pc.setLocalDescription(offer);
    }).then(() => {
        // wait for ICE gathering to complete
        return new Promise((resolve) => {
            if (state.pc.iceGatheringState === 'complete') {
                resolve();
            } else {
                const checkState = () => {
                    if (state.pc.iceGatheringState === 'complete') {
                        state.pc.removeEventListener('icegatheringstatechange', checkState);
                        resolve();
                    }
                };
                state.pc.addEventListener('icegatheringstatechange', checkState);
            }
        });
    }).then(() => {
        var offer = state.pc.localDescription;
        return fetch('/offer', {
            body: JSON.stringify({
                sdp: offer.sdp,
                type: offer.type,
            }),
            headers: {
                'Content-Type': 'application/json'
            },
            method: 'POST'
        });
    }).then((response) => {
        return response.json();
    }).then((answer) => {
        return state.pc.setRemoteDescription(answer);
    }).catch((e) => {
        alert(e);
    });
}

function trim(str, maxLength = 50){
    return str.length <= maxLength ? str : str.substring(0, maxLength - 4) + " ..."
}
function start() {
    stop()

    const config = {
        sdpSemantics: 'unified-plan'
    };

    if (document.getElementById('use-stun').checked) {
        config.iceServers = [{ urls: ['stun:stun.l.google.com:19302'] }];
    }

    state.pc = new RTCPeerConnection(config);
    state.pc.onconnectionstatechange = (ev) => {
        getcconnectionstatus()
    }
    state.dc = state.pc.createDataChannel("chat")
    state.dc.onopen = (ev) => {
        console.log("Data channel is open and ready to use");
        send_message_on_chat("Hello server");
    }
    state.dc.onmessage = (ev) => {
        console.log('Received message: ' + trim(ev.data));
        if(ev.data === "ready") {
            record()
        }
        if(ev.data.startsWith("Human:") || ev.data.startsWith("AI:") || ev.data.startsWith("image:") || ev.data.startsWith("uploading:")) {
            logmessage(ev.data)
        }
        if(ev.data.startsWith("uploaded:")){
            logmessage(ev.data)
        }
        if(ev.data.startsWith("playing:")) {
            if(!ev.data.endsWith("silence")) {
                hideElement(processing)
                showElement(wave)
            } else {
                hideElement(wave)
                hideElement(waitRecordDiv)
                showElement(startRecordDiv)
            }
        }
    }
    state.dc.onclose = () => {
        console.log("Data channel is closed");
    }

    // connect audio / video
    state.pc.ontrack = (ev) => {
        console.log('Received remote stream');
        document.querySelector('audio#remoteAudio').srcObject = ev.streams[0];
    }
    // Adding tracks
    // stream.getAudioTracks().forEach((track) => pc.addTrack(track, stream))
    // document.querySelector('button#start').style.display = 'none';
    //negotiate()
    getMedia()
    showElement(chatNameContainer)
    showElement(presetsSelect)
    showElement(modelsSelect)
    showElement(messagesContainer)
    showElement(startRecordDiv)
    hideElement(waitRecordDiv)
    showElement(cameraImg)
    //document.querySelector('button#stop').style.display = 'inline-block';
}
function logmessage(message) {
    let log = document.querySelector("div.conversation-container")
    let splits = message.split(": ")
    if (splits.length > 1) {
        let messageText = splits.slice(1).join(": ")
        if (messageText.trim().length > 0) {
            let newMessage = document.createElement("div")
            newMessage.classList.add("message")
            if (splits[0] === "Human" || splits[0] === "uploaded" || splits[0] === "uploading") {
                newMessage.classList.add("sent")
                if (splits[0] === "uploaded") {
                    hideElement(processing)
                    hideElement(waitRecordDiv)
                    showElement(startRecordDiv)
                }
            } else {
                newMessage.classList.add("received")
            }
            if (splits[0] === "image" || splits[0] === "uploading") {
                let image = document.createElement("img")
                image.src = splits[1]
                newMessage.append(image)
                if(splits[0] === "image") {
                    hideElement(processing)
                }
            } else {
                newMessage.textContent = messageText
            }
            log.appendChild(newMessage)
            log.scrollTop = log.scrollHeight
        }
    }
}
function getMedia(){
    const constraints = {
        audio: true,
        video: false
    };
    navigator.mediaDevices
        .getUserMedia(constraints)
        .then(handleSuccess)
        .catch(handleFailure);
}

function stop() {
    hideElement(processing)
    hideElement(startRecordDiv)
    showElement(waitRecordDiv)
    hideElement(chatNameContainer)
    hideElement(presetsSelect)
    hideElement(modelsSelect)
    hideElement(cameraImg)
    if(state.pc) {
        // close peer connection
        setTimeout(() => {
            state.pc.close();
            getcconnectionstatus()
            state = {pc:null, dc:null, stream:null}
        }, 500);
    }
}

function record(){
    hideElement(wave)
    hideElement(startRecordDiv)
    showElement(stopRecordDiv)
    //getMedia()
    send_message_on_chat("start_recording")
}

function stopRecord() {
    send_message_on_chat("stop_recording")
    showElement(processing)
    hideElement(stopRecordDiv)
    showElement(waitRecordDiv)
}

function send_message_on_chat(message) {
    console.log(`Sending: ${message}`)
    state.dc.send(message)
}

function getMimeTypeFromData(data) {

  const len = 4
  if (data.length >= len) {
    let signatureArr = new Array(len)
    for (let i = 0; i < len; i++)
      signatureArr[i] = data[i].toString(16)
    const signature = signatureArr.join('').toUpperCase()

    switch (signature) {
      case '89504E47':
        return 'image/png'
      case '47494638':
        return 'image/gif'
      case '25504446':
        return 'application/pdf'
      case 'FFD8FFDB':
      case 'FFD8FFE0':
        return 'image/jpeg'
      case '504B0304':
        return 'application/zip'
      default:
        return null
    }
  }
  return null
}

function splitStringToMax(str, maxLength) {
  const result = [];
  let i = 0;
  while (i < str.length) {
    result.push(str.substring(i, i + maxLength));
    i += maxLength;
  }
  return result;
}
function processPhotoUpload(fileName, buffer) {
    const data = new Uint8Array(buffer)
    if(data.length > 150 * 1024){
        logmessage(`AI: File uploads larger than 150kb are not allowed. You attempted to upload file of size ${Math.ceil(data.length / 1024)} kb.`)
        fileInput.value = null
        return
    }
    const base64String = btoa(String.fromCharCode(...data));
    let mimeType = getMimeTypeFromData(data)
    if (!mimeType) return null
    const fileNameImageUrl = `${fileName}:${mimeType}:${base64String}`
    showElement(processing)
    hideElement(startRecordDiv)
    showElement(waitRecordDiv)
    const maxMessageSize = state.pc.sctp.maxMessageSize
    logmessage(`Human: Uploading ${fileName}`)
    send_message_on_chat("upload:START")
    splitStringToMax(fileNameImageUrl, maxMessageSize - 7).forEach((chunk) => {
        state.dc.send(`upload:${chunk}`)
    })
    send_message_on_chat("upload:DONE")
    logmessage(`uploading: data:${mimeType};base64,${base64String}`)
    fileInput.value = null
}
function uploadPhoto(){
    fileInput.click()
}
function getResponse(){
    send_message_on_chat("get_response")
}
function getSilence(){
    send_message_on_chat("get_silence")
}
function handleSuccess(stream) {
    const tracks = stream.getAudioTracks()
    console.log("Received: ", tracks.length, " tracks")
    state.stream = stream
    state.stream.getAudioTracks().forEach((track) =>{
        state.pc.addTrack(track)
    })
    negotiate()
}

function handleFailure(error) {
    console.log('navigator.getUserMedia error: ', error);
}

function showElement(element) {
    element.classList.remove("d-none")
}
function hideElement(element) {
    element.classList.add("d-none")
}

function changePreset(){
    let preset = document.querySelector("select#presets").value
    send_message_on_chat("preset:" + preset)
}
function changeModel() {
    let model = document.querySelector("select#models").value
    send_message_on_chat("model:" + model)
    chatNameContainer.textContent = model
}

document.addEventListener('DOMContentLoaded', () => {
    getcconnectionstatus()
    powerButton.onclick = () => {
        if(state.pc && state.pc.connectionState === "connected") {
            stop()
            powerButton.classList.remove("text-danger")
            powerButton.classList.add("text-success")
        } else {
            start()
            powerButton.classList.remove("text-success")
            powerButton.classList.add("text-danger")
        }
    }
    fileInput.addEventListener("change",(ev) => {
        console.log(`Files: ${ev.target.files.length}`)
        if(ev.target.files.length > 0){
            let photo = ev.target.files[0]
            const fileName = photo.name
            photo
                .arrayBuffer()
                .then((buffer) => processPhotoUpload(fileName, buffer))
        }
    })
})