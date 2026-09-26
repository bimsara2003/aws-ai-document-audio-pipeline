"""Demonstration pipeline for AWS document and speech AI services.

The script expects an input PDF in S3 and uses the default Boto3 credential
chain. In SageMaker, prefer the notebook execution role over static keys.
"""

from __future__ import annotations

import json
import os
import time
import urllib.request
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


REGION = os.getenv("AWS_REGION", "us-east-1")
BUCKET = os.getenv("AWS_BUCKET")
INPUT_KEY = os.getenv("AWS_INPUT_KEY")
OUTPUT_PREFIX = os.getenv("AWS_OUTPUT_PREFIX", "pipeline-output").strip("/")
TARGET_LANGUAGE = os.getenv("TARGET_LANGUAGE", "fr")

session = boto3.Session(region_name=REGION)
s3 = session.client("s3")
textract = session.client("textract")
comprehend = session.client("comprehend")
translate = session.client("translate")
polly = session.client("polly")
transcribe = session.client("transcribe")


def extract_text_from_pdf(bucket: str, key: str) -> str:
    """Run Textract asynchronous text detection and collect all detected lines."""
    started = textract.start_document_text_detection(
        DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}}
    )
    job_id = started["JobId"]

    while True:
        result = textract.get_document_text_detection(JobId=job_id, MaxResults=1000)
        status = result["JobStatus"]
        if status == "SUCCEEDED":
            break
        if status == "FAILED":
            raise RuntimeError(f"Textract job failed: {result.get('StatusMessage', 'no details')}")
        time.sleep(5)

    lines: list[str] = []
    while True:
        lines.extend(
            block["Text"]
            for block in result.get("Blocks", [])
            if block.get("BlockType") == "LINE" and "Text" in block
        )
        next_token = result.get("NextToken")
        if not next_token:
            break
        result = textract.get_document_text_detection(
            JobId=job_id, MaxResults=1000, NextToken=next_token
        )
    return "\n".join(lines)


def analyze_sentiment(text: str) -> dict:
    """Analyze a short UTF-8-safe sample with Amazon Comprehend."""
    sample = text.encode("utf-8")[:4500].decode("utf-8", errors="ignore")
    if not sample:
        raise ValueError("No text was extracted to analyze.")
    return comprehend.detect_sentiment(Text=sample, LanguageCode="en")


def translate_text(text: str, target_language: str) -> str:
    """Translate a UTF-8-safe sample of the extracted text."""
    sample = text.encode("utf-8")[:4500].decode("utf-8", errors="ignore")
    if not sample:
        raise ValueError("No text was extracted to translate.")
    response = translate.translate_text(
        Text=sample,
        SourceLanguageCode="auto",
        TargetLanguageCode=target_language,
    )
    return response["TranslatedText"]


def synthesize_speech(text: str, bucket: str, filename: str) -> tuple[bytes, str]:
    """Generate an MP3 using Polly, save it locally, and upload it to S3."""
    response = polly.synthesize_speech(
        Text=text[:3000], OutputFormat="mp3", VoiceId="Matthew"
    )
    audio_bytes = response["AudioStream"].read()
    object_key = f"{OUTPUT_PREFIX}/audio/{filename}.mp3"
    s3.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=audio_bytes,
        ContentType="audio/mpeg",
    )

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    (output_dir / f"{filename}.mp3").write_bytes(audio_bytes)
    return audio_bytes, object_key


def transcribe_audio(bucket: str, audio_key: str) -> str:
    """Submit an asynchronous Transcribe job and fetch its transcript."""
    job_name = f"ai-pipeline-{uuid.uuid4().hex}"
    transcribe.start_transcription_job(
        TranscriptionJobName=job_name,
        Media={"MediaFileUri": f"s3://{bucket}/{audio_key}"},
        MediaFormat="mp3",
        LanguageCode="en-US",
    )

    while True:
        response = transcribe.get_transcription_job(TranscriptionJobName=job_name)
        job = response["TranscriptionJob"]
        status = job["TranscriptionJobStatus"]
        if status == "COMPLETED":
            transcript_uri = job["Transcript"]["TranscriptFileUri"]
            with urllib.request.urlopen(transcript_uri, timeout=30) as response_stream:
                transcript_data = json.loads(response_stream.read())
            return transcript_data["results"]["transcripts"][0]["transcript"]
        if status == "FAILED":
            raise RuntimeError(f"Transcribe job failed: {job.get('FailureReason', 'no details')}")
        time.sleep(5)


def main() -> None:
    if not BUCKET or not INPUT_KEY:
        raise SystemExit(
            "Set AWS_BUCKET and AWS_INPUT_KEY environment variables before running."
        )

    try:
        extracted_text = extract_text_from_pdf(BUCKET, INPUT_KEY)
        if not extracted_text.strip():
            raise RuntimeError("Textract completed but returned no text.")

        sentiment = analyze_sentiment(extracted_text)
        translated = translate_text(extracted_text, TARGET_LANGUAGE)
        filename = f"speech-{uuid.uuid4().hex[:8]}"
        _audio_bytes, audio_key = synthesize_speech(extracted_text, BUCKET, filename)
        transcript = transcribe_audio(BUCKET, audio_key)

        print("Extracted text sample:\n", extracted_text[:1500])
        print("\nSentiment:\n", json.dumps(sentiment, indent=2, default=str))
        print("\nTranslation sample:\n", translated[:1500])
        print(f"\nAudio saved to s3://{BUCKET}/{audio_key}")
        print("\nTranscription:\n", transcript)
    except (ClientError, RuntimeError, ValueError) as error:
        raise SystemExit(f"Pipeline failed: {error}") from error


if __name__ == "__main__":
    main()
