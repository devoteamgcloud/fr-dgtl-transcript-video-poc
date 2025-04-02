import argparse
import asyncio
import subprocess
import os
import time
from typing import List, Tuple
from google.cloud import speech, storage

DEFAULT_SPEECH_TO_TEXT_TIMEOUT = 3600 
os.environ["GRPC_VERBOSITY"] = "ERROR"

BUCKET_NAME = os.getenv("BUCKET_NAME")
SEGMENT_DIVIDER = os.getenv("SEGMENT_DIVIDER")

# Defined for each audio file from global video length and segment divider
segment_duration = None


def extract_audio_from_gcs(filename: str, output_audio: str) -> bool:
    """
    Extracts audio from a video file stored in Google Cloud Storage using ffmpeg.

    Args:
        input_gcs_uri: The GCS URI of the input video file (e.g., "gs://your-bucket/your-video.mp4").
        output_audio: The path to the output audio file (default: "audio.wav").

    Returns:
        True if the extraction was successful, False otherwise.
    """
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", filename, "-vn", output_audio],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error extracting audio: {e}")
        print(f"ffmpeg output(stderr): {e.stderr}")
        return False
    except FileNotFoundError:
        print("ffmpeg not found. Please ensure ffmpeg is installed and in your PATH.")
        return False


def convert_to_mono(input_file: str, output_file: str):
    """Converts a stereo audio file to mono using ffmpeg-python."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_file, "-ac", "1", output_file],
            check=True,
            capture_output=True,
            text=True,
        )
        print(f"Successfully converted {input_file} to mono: {output_file}\n")
        os.remove(input_file)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error extracting audio: {e}")
        print(f"ffmpeg output(stderr): {e.stderr}")
        return False
    except FileNotFoundError:
        print("ffmpeg not found. Please ensure ffmpeg is installed and in your PATH.")
        return False


def split_audio_into_segments(src_audio_filename: str) -> List[Tuple[str, str]]:
    """Splits an audio file in GCS into segments and returns a list of GCS URIs for each segment.

    Args:
        input_gcs_uri: The GCS URI of the input audio file.
        segment_duration_seconds: The duration of each segment in seconds (default: 5 minutes).

    Returns:
        A list of tuples, where each tuple contains:
        - The GCS URI of the segment.
        - The start time of the segment in HH:MM:SS format.
    """

    # Get the duration of the audio using ffprobe
    duration_process = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            src_audio_filename,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    duration = float(duration_process.stdout.strip())

    global segment_duration
    segment_duration = duration // SEGMENT_DIVIDER

    print(
        f"Audio duration: {duration} seconds: splitting into {int(segment_duration)}-second segments.\n"
    )

    segments = []
    start_time = 0
    segment_index = 1
    while start_time < duration:
        end_time = min(start_time + segment_duration, duration)
        start_time_str = f"{int(start_time // 3600):02d}:{int((start_time % 3600) // 60):02d}:{int(start_time % 60):02d}"
        segment_filename = (
            f"{os.path.splitext(src_audio_filename)[0]}_{segment_index}.wav"
        )
        output_gcs_uri = f"gs://{BUCKET_NAME}/{segment_filename}"

        # Extract the segment using ffmpeg and upload it to GCS
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                start_time_str,
                "-i",
                src_audio_filename,
                "-to",
                f"{end_time - start_time}",
                "-ac",
                "1",
                "-acodec",
                "pcm_s16le",  # Ensure a compatible audio codec
                segment_filename,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        storage_client = storage.Client()
        bucket = storage_client.bucket(BUCKET_NAME)
        blob = bucket.blob(segment_filename)
        try:
            print(f"Starting audio file segment #{segment_index} upload ... ")
            blob.upload_from_filename(segment_filename)
            print(
                f"File {segment_filename} uploaded to {BUCKET_NAME}/{segment_filename}.\n"
            )
            os.remove(segment_filename)
        except Exception as e:
            print(f"Error uploading {segment_filename}: {e}")
            exit(1)
        segments.append((output_gcs_uri, start_time_str))
        start_time = end_time
        segment_index += 1
    return segments


async def run_async_transcribe(gcs_uri: str, start_time: str) -> None:
    """Asynchronously transcribes the audio file specified by the gcs_uri."""

    client = speech.SpeechAsyncClient()

    audio = speech.RecognitionAudio(uri=gcs_uri)

    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        language_code="fr-FR",
        enable_word_time_offsets=True,
    )

    operation = await client.long_running_recognize(config=config, audio=audio)

    print(f"{gcs_uri}...")
    resp = await operation.result(timeout=DEFAULT_SPEECH_TO_TEXT_TIMEOUT)
    return resp.results, start_time


async def transcript_from_local_file(filename: str):
    # Example usage:
    tmp_audio_file = f"{filename}-tmp_audio.wav"
    converted_audio_file = f"{filename}-audio.wav"

    print(f"Extracting audio from {filename}...")
    if extract_audio_from_gcs(f"videos/{filename}", tmp_audio_file):
        print(f"Audio extracted successfully to {tmp_audio_file}\n")
        print("Converting stereo to mono ... ")
        convert_to_mono(tmp_audio_file, converted_audio_file)
    else:
        print("Audio extraction failed.")
        exit(1)

    segments = split_audio_into_segments(converted_audio_file)

    tasks = []
    print("Starting audio transcription... ")
    for segment in segments:
        tasks.append(asyncio.create_task(run_async_transcribe(segment[0], segment[1])))

    content = await asyncio.gather(*tasks)
    for transcript, start_time in content:
        for result in transcript:
            print(f"{start_time} - {result.alternatives[0].transcript}")


# - - - - - - - - - - - - - - - - - - - - - - - - -
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Transcribe an audio file from a video.")
    parser.add_argument("video", type=str, help="The name of the video file to transcribe.")
    args = parser.parse_args()

    start = time.time()
    asyncio.run(transcript_from_local_file(args.video))
    end = time.time()
    print(f"Time taken: {end - start} seconds.")
