# SPDX-FileCopyrightText: 2022-present deepset GmbH <info@deepset.ai>
#
# SPDX-License-Identifier: Apache-2.0
import os
import platform
from pathlib import Path

import pytest
import numpy as np

try:
    import soundfile as sf
    import ffmpeg

    soundfile_not_found = False
except:
    soundfile_not_found = True

from transformers import WhisperProcessor, WhisperForConditionalGeneration

from haystack.schema import Span, Answer, Document
from text2speech import AnswerToSpeech, DocumentToSpeech
from text2speech.utils import TextToSpeech


SAMPLES_PATH = Path(__file__).parent / "samples"


class WhisperHelper:
    def __init__(self, model):
        self._processor = WhisperProcessor.from_pretrained(model)
        self._model = WhisperForConditionalGeneration.from_pretrained(model)
        self._model.config.forced_decoder_ids = None

    def transcribe(self, media_file: str):
        output, _ = (
            ffmpeg.input(media_file)
            .output("-", format="s16le", acodec="pcm_s16le", ac=1, ar=16000)
            .run(cmd=["ffmpeg", "-nostdin"], capture_stdout=True, capture_stderr=True)
        )
        data = np.frombuffer(output, np.int16).flatten().astype(np.float32) / 32768.0

        features = self._processor(data, sampling_rate=16000, return_tensors="pt").input_features
        tokens = self._model.generate(features)

        return self._processor.batch_decode(tokens, skip_special_tokens=True)


@pytest.fixture(scope="session", autouse=True)
def whisper_helper():
    return WhisperHelper("openai/whisper-medium")


@pytest.mark.integration
class TestTextToSpeech:
    def test_text_to_speech_audio_data(self, tmp_path, whisper_helper: WhisperHelper):
        text2speech = TextToSpeech(
            model_name_or_path="espnet/kan-bayashi_ljspeech_vits",
            transformers_params={"seed": 4535, "always_fix_seed": True},
        )

        audio_data = text2speech.text_to_audio_data(text="answer")

        sf.write(
            data=audio_data,
            file=str(tmp_path / "audio1.wav"),
            format="wav",
            subtype="PCM_16",
            samplerate=text2speech.model.fs,
        )

        expected_doc = whisper_helper.transcribe(str(SAMPLES_PATH / "answer.wav"))
        generated_doc = whisper_helper.transcribe(str(tmp_path / "audio1.wav"))

        assert expected_doc[0] in generated_doc[0]

    def test_text_to_speech_audio_file(self, tmp_path, whisper_helper: WhisperHelper):
        text2speech = TextToSpeech(
            model_name_or_path="espnet/kan-bayashi_ljspeech_vits",
            transformers_params={"seed": 4535, "always_fix_seed": True},
        )

        audio_file = text2speech.text_to_audio_file(text="answer", generated_audio_dir=tmp_path / "test_audio")
        assert os.path.exists(audio_file)

        expected_doc = whisper_helper.transcribe(str(SAMPLES_PATH / "answer.wav"))
        generated_doc = whisper_helper.transcribe(str(audio_file))

        assert expected_doc[0] in generated_doc[0]

    @pytest.mark.xfail(reason="known issue converting to MP3")
    def test_text_to_speech_compress_audio(self, tmp_path, whisper_helper: WhisperHelper):
        text2speech = TextToSpeech(
            model_name_or_path="espnet/kan-bayashi_ljspeech_vits",
            transformers_params={"seed": 4535, "always_fix_seed": True},
        )
        expected_audio_file = SAMPLES_PATH / "answer.wav"
        audio_file = text2speech.text_to_audio_file(
            text="answer", generated_audio_dir=tmp_path / "test_audio", audio_format="mp3"
        )
        assert os.path.exists(audio_file)
        assert audio_file.suffix == ".mp3"

        expected_doc = whisper_helper.transcribe(str(expected_audio_file))
        generated_doc = whisper_helper.transcribe(str(audio_file))

        assert expected_doc[0] in generated_doc[0]

    def test_text_to_speech_naming_function(self, tmp_path, whisper_helper: WhisperHelper):
        text2speech = TextToSpeech(
            model_name_or_path="espnet/kan-bayashi_ljspeech_vits",
            transformers_params={"seed": 4535, "always_fix_seed": True},
        )
        expected_audio_file = SAMPLES_PATH / "answer.wav"
        audio_file = text2speech.text_to_audio_file(
            text="answer", generated_audio_dir=tmp_path / "test_audio", audio_naming_function=lambda text: text
        )
        assert os.path.exists(audio_file)
        assert audio_file.name == expected_audio_file.name

        expected_doc = whisper_helper.transcribe(str(expected_audio_file))
        generated_doc = whisper_helper.transcribe(str(audio_file))

        assert expected_doc[0] in generated_doc[0]


@pytest.mark.integration
class TestAnswerToSpeech:
    def test_answer_to_speech(self, tmp_path, whisper_helper: WhisperHelper):
        text_answer = Answer(
            answer="answer",
            type="extractive",
            context="the context for this answer is here",
            offsets_in_document=[Span(31, 37)],
            offsets_in_context=[Span(21, 27)],
            meta={"some_meta": "some_value"},
        )
        expected_audio_answer = SAMPLES_PATH / "answer.wav"
        expected_audio_context = SAMPLES_PATH / "the context for this answer is here.wav"

        answer2speech = AnswerToSpeech(
            generated_audio_dir=tmp_path / "test_audio",
            audio_params={"audio_naming_function": lambda text: text},
            transformers_params={"seed": 4535, "always_fix_seed": True},
        )
        results, _ = answer2speech.run(answers=[text_answer])

        audio_answer: Answer = results["answers"][0]
        assert isinstance(audio_answer, Answer)
        assert audio_answer.answer.split(os.path.sep)[-1] == str(expected_audio_answer).split(os.path.sep)[-1]
        assert audio_answer.context.split(os.path.sep)[-1] == str(expected_audio_context).split(os.path.sep)[-1]
        assert audio_answer.offsets_in_document == [Span(31, 37)]
        assert audio_answer.offsets_in_context == [Span(21, 27)]
        assert audio_answer.meta["answer_text"] == "answer"
        assert audio_answer.meta["context_text"] == "the context for this answer is here"
        assert audio_answer.meta["some_meta"] == "some_value"
        assert audio_answer.meta["audio_format"] == "wav"

        expected_doc = whisper_helper.transcribe(str(expected_audio_answer))
        generated_doc = whisper_helper.transcribe(str(audio_answer.answer))

        assert expected_doc[0] in generated_doc[0]


@pytest.mark.integration
class TestDocumentToSpeech:
    def test_document_to_speech(self, tmp_path, whisper_helper: WhisperHelper):
        text_doc = Document(
            content="this is the content of the document", content_type="text", meta={"name": "test_document.txt"}
        )
        expected_audio_content = SAMPLES_PATH / "this is the content of the document.wav"

        doc2speech = DocumentToSpeech(
            generated_audio_dir=tmp_path / "test_audio",
            audio_params={"audio_naming_function": lambda text: text},
            transformers_params={"seed": 4535, "always_fix_seed": True},
        )

        results, _ = doc2speech.run(documents=[text_doc])

        audio_doc: Document = results["documents"][0]
        assert isinstance(audio_doc, Document)
        assert audio_doc.content_type == "audio"
        assert audio_doc.content.split(os.path.sep)[-1] == str(expected_audio_content).split(os.path.sep)[-1]
        assert audio_doc.meta["content_text"] == "this is the content of the document"
        assert audio_doc.meta["name"] == "test_document.txt"
        assert audio_doc.meta["audio_format"] == "wav"

        expected_doc = whisper_helper.transcribe(str(expected_audio_content))
        generated_doc = whisper_helper.transcribe(str(audio_doc.content))

        assert expected_doc[0] in generated_doc[0]
