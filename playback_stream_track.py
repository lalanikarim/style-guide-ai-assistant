import asyncio
from typing import Optional

from aiortc import MediaStreamTrack, RTCDataChannel
from aiortc.contrib.media import MediaPlayer
import os
import logging

from aiortc.mediastreams import MediaStreamError

logger = logging.getLogger("pc")


class PlaybackStreamTrack(MediaStreamTrack):
    kind = "audio"
    _response_ready: bool = False
    previous_response_silence: bool = False
    track: MediaStreamTrack = None
    filename: str = None
    counter: int = 0
    time: float = 0.0
    channel: Optional[RTCDataChannel] = None

    def __init__(self):
        super().__init__()  # don't forget this!

    def set_filename(self, filename: str):
        self.filename = filename

    def play_silence(self):
        self._response_ready = False
        # self.select_track()

    def play_response(self):
        if len(self.filename) > 0 and os.path.isfile(self.filename):
            self._response_ready = True
            # self.select_track()
        else:
            raise ValueError(f"filename not set or file doesn't exist. {self.filename}")

    def select_track(self):
        logger.debug("Select track - response_ready %s", self._response_ready)
        if self._response_ready:
            self.track = MediaPlayer(self.filename, format="wav", loop=False).audio
            logger.debug("Playback track selected")
        else:
            self.track = MediaPlayer("silence.wav", format="wav", loop=False).audio
            logger.debug("Silence track selected")
        if self.channel is not None and self.channel.readyState == "open":
            if self._response_ready:
                self.channel.send("playing: response")
                self.previous_response_silence = False
                logger.debug("Playback track playing")
            else:
                if not self.previous_response_silence:
                    self.channel.send("playing: silence")
                    self.previous_response_silence = True
                    logger.debug("Silence track playing")

    async def recv(self):
        self.counter += 1
        if self.track is None:
            logger.debug("No track selected. Selecting track")
            self.select_track()
        try:
            async with asyncio.timeout(1):
                frame = await self.track.recv()
        except (MediaStreamError, TimeoutError) as e:
            self.select_track()
            if self._response_ready:
                self._response_ready = False
            frame = await self.track.recv()
        except Exception as e:
            logger.error(e)
            raise e
        if frame.pts < frame.sample_rate * self.time:
            frame.pts = frame.sample_rate * self.time
        self.time += 0.02
        return frame
