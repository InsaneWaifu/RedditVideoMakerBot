#!/usr/bin/env python3
from pathlib import Path
from typing import Tuple
import re

# import sox
# from mutagen import MutagenError
# from mutagen.mp3 import MP3, HeaderNotFoundError
import translators as ts
from rich.progress import track
from moviepy.editor import AudioFileClip, CompositeAudioClip, concatenate_audioclips
from utils.console import print_step, print_substep
from utils.voice import sanitize_text
from utils import settings

DEFAULT_MAX_LENGTH: int = 50  # video length variable


class TTSEngine:

    """Calls the given TTS engine to reduce code duplication and allow multiple TTS engines.

    Args:
        tts_module          : The TTS module. Your module should handle the TTS itself and saving to the given path under the run method.
        reddit_object         : The reddit object that contains the posts to read.
        path (Optional)       : The unix style path to save the mp3 files to. This must not have leading or trailing slashes.
        max_length (Optional) : The maximum length of the mp3 files in total.

    Notes:
        tts_module must take the arguments text and filepath.
    """

    def __init__(
        self,
        tts_module,
        reddit_object: dict,
        path: str = "assets/temp/",
        max_length: int = DEFAULT_MAX_LENGTH,
        last_clip_length: int = 0,
    ):
        self.racked_up_split_length = 0
        self.tts_module = tts_module()
        self.reddit_object = reddit_object
        self.redditid = re.sub(r"[^\w\s-]", "", reddit_object["thread_id"])
        self.path = path + self.redditid + "/mp3"
        self.max_length = max_length
        self.length = 0
        self.last_clip_length = last_clip_length

    def run(self) -> Tuple[int, int]:

        Path(self.path).mkdir(parents=True, exist_ok=True)

        # This file needs to be removed in case this post does not use post text, so that it won't appear in the final video
        try:
            Path(f"{self.path}/posttext.mp3").unlink()
        except OSError:
            pass

        print_step("Saving Text to MP3 files...")

        self.call_tts("title", process_text(self.reddit_object["thread_title"]))
        processed_text = process_text(self.reddit_object["thread_post"])
        if processed_text != "" and settings.config["settings"]["storymode"] == True:
            self.call_tts("posttext", processed_text)

        idx = None
        for idx, comment in track(enumerate(self.reddit_object["comments"]), "Saving..."):
            # ! Stop creating mp3 files if the length is greater than max length.
            if self.length > self.max_length:
                self.length -= self.last_clip_length
                idx -= 1
                break
            if (
                len(comment["comment_body"]) > self.tts_module.max_chars
            ):  # Split the comment if it is too long
                self.split_post(comment["comment_body"], idx)  # Split the comment
            else:  # If the comment is not too long, just call the tts engine
                self.call_tts(f"{idx}", process_text(comment["comment_body"]))

        print_substep("Saved Text to MP3 files successfully.", style="bold green")
        return self.length, idx

    def split_post(self, text: str, idx: int):
        split_files = []
        split_text = [
            x.group().strip()
            for x in re.finditer(
                r" *(((.|\n){0," + str(self.tts_module.max_chars) + "})(\.|.$))", text
            )
        ]
        offset = 0
        for idy, text_cut in enumerate(split_text):
            # print(f"{idx}-{idy}: {text_cut}\n")
            new_text = process_text(text_cut)
            if not new_text or new_text.isspace():
                offset += 1
                continue

            if not self.call_tts(f"{idx}-{idy - offset}.part", new_text, True):
                # Failed for whatever reason, seems to happen with tiktok and split posts.
                self.length -= self.racked_up_split_length
                print("Failed")
                return
            split_files.append(AudioFileClip(f"{self.path}/{idx}-{idy - offset}.part.mp3"))
        self.racked_up_split_length = 0
        CompositeAudioClip([concatenate_audioclips(split_files)]).write_audiofile(
            f"{self.path}/{idx}.mp3", fps=44100, verbose=False, logger=None
        )

        for i in split_files:
            name = i.filename
            i.close()
            Path(name).unlink()

        # for i in range(0, idy + 1):
        # print(f"Cleaning up {self.path}/{idx}-{i}.part.mp3")

        # Path(f"{self.path}/{idx}-{i}.part.mp3").unlink()

    def call_tts(self, filename: str, text: str, split=False):
        self.tts_module.run(text, filepath=f"{self.path}/{filename}.mp3")
        # try:
        #     self.length += MP3(f"{self.path}/{filename}.mp3").info.length
        # except (MutagenError, HeaderNotFoundError):
        #     self.length += sox.file_info.duration(f"{self.path}/{filename}.mp3")
        try:
            clip = AudioFileClip(f"{self.path}/{filename}.mp3")
            self.last_clip_length = clip.duration
            self.length += clip.duration
            if split:
                self.racked_up_split_length += clip.duration
            clip.close()
            return True
        except:
            return False


def process_text(text: str):
    lang = settings.config["reddit"]["thread"]["post_lang"]
    new_text = sanitize_text(text)
    if lang:
        print_substep("Translating Text...")
        translated_text = ts.google(text, to_language=lang)
        new_text = sanitize_text(translated_text)
    return new_text
