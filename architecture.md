# Architecture and data flow

The project is orchestrated by a Python process running in a SageMaker Jupyter notebook (or locally). Boto3 makes signed AWS API requests using the execution role or the configured local credential provider.

![AWS AI document and audio pipeline architecture](screenshots/architecture.png)

Open the [scalable SVG diagram](screenshots/architecture.svg). The editable diagram source is [build_architecture_diagram.py](scripts/build_architecture_diagram.py); its service icons are stored under [screenshots/aws-icons](screenshots/aws-icons/README.md).

## Responsibility boundaries

- **SageMaker notebook/Python:** orchestration and presentation; it does not host the AI service APIs.
- **S3:** durable object storage for the source PDF and audio artifacts.
- **Textract:** document text extraction.
- **Comprehend:** sentiment classification.
- **Translate:** language translation.
- **Polly:** text-to-speech synthesis.
- **Transcribe:** asynchronous speech-to-text transcription.

## Security boundary

The notebook should use a narrowly scoped IAM execution role. Grant only the required actions and only the necessary S3 bucket/prefix. Keep source documents private, use encryption, avoid logging sensitive document contents, and never commit AWS credentials or real customer documents.
