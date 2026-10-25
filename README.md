# invoke_model_ssm.py

Calls an Amazon Bedrock model with the **InvokeModel** API, using a request body in that model's own JSON format. The model ID and inference settings come from **AWS Systems Manager (SSM) Parameter Store**, so you can switch models without changing code.

Part of the AIP-C01 (AWS Certified Generative AI Developer - Professional) hands-on labs, Lab 1.1.

## What it does

1. Reads a JSON config from an SSM parameter (default `/aipc01/model-config`).
2. Detects the model provider from the model ID, ignoring cross-Region prefixes such as `us.` and `global.`.
3. Builds the request body in that provider's format.
4. Calls `bedrock-runtime` `InvokeModel`.
5. Reads the provider's response format and prints the answer, token counts and latency.

## Supported model families

| Provider | Example model ID | Request body shape |
| --- | --- | --- |
| Amazon Nova | `us.amazon.nova-lite-v1:0` | `schemaVersion`, `messages`, `inferenceConfig`, `system` |
| Amazon Titan Text | `amazon.titan-text-express-v1` | `inputText`, `textGenerationConfig` |
| Anthropic Claude | `us.anthropic.claude-sonnet-4-5-...` | `anthropic_version`, `max_tokens`, `messages`, `system` |
| Meta Llama 3 | `meta.llama3-1-8b-instruct-v1:0` | `prompt` (chat template), `max_gen_len` |
| Mistral | `mistral.mistral-7b-instruct-v0:2` | `prompt` (`[INST]`), `max_tokens` |

> **AWS India (AISPL) accounts:** third-party models (Anthropic, Meta, Mistral) need an AWS Marketplace subscription, which often fails with `INVALID_PAYMENT_INSTRUMENT`. Use Amazon Nova or Titan models instead.

## Prerequisites

- An AWS account with Amazon Bedrock available in your Region (for example `us-east-1`)
- AWS CLI v2, configured (`aws sts get-caller-identity` returns your ARN)
- [uv](https://docs.astral.sh/uv/) (or Python 3.10+ with pip)
- IAM permissions:
  - `ssm:GetParameter` on the parameter
  - `bedrock:InvokeModel` on the model or inference profile
  - `kms:Decrypt` if the parameter is a `SecureString`

## Setup

### 1. Install dependencies

```powershell
uv add boto3
```

or, without uv: `pip install boto3`

### 2. Create the model config file

Save as `model-config.json`:

```json
{
  "modelId": "us.amazon.nova-lite-v1:0",
  "region": "us-east-1",
  "maxTokens": 512,
  "temperature": 0.5,
  "topP": 0.9,
  "systemPrompt": "You are a concise AWS tutor."
}
```

| Key | Required | Default | Description |
| --- | --- | --- | --- |
| `modelId` | Yes | none | Bedrock model ID or inference profile ID |
| `region` | No | the SSM Region | Region used for the Bedrock call |
| `maxTokens` | No | 512 | Maximum output tokens |
| `temperature` | No | 0.5 | Randomness (0 to 1) |
| `topP` | No | 0.9 | Nucleus sampling |
| `systemPrompt` | No | none | System instructions |
| `extraBody` | No | none | JSON object merged into the request body as-is, for model-specific fields |

The parameter can also hold a plain model ID string instead of JSON. In that case the defaults above are used.

### 3. Store it in SSM Parameter Store

Works in Windows PowerShell, cmd, macOS and Linux:

```powershell
aws ssm put-parameter --name /aipc01/model-config --type String --region us-east-1 --value file://model-config.json --overwrite
```

Check it:

```powershell
aws ssm get-parameter --name /aipc01/model-config --region us-east-1 --query Parameter.Value --output text
```

## Usage

```powershell
uv run invoke_model_ssm.py "Explain RAG in two sentences" --ssm-region us-east-1
```

| Option | Default | Description |
| --- | --- | --- |
| `prompt` (positional) | none | Text sent to the model |
| `--param` | `/aipc01/model-config` | SSM parameter name |
| `--ssm-region` | CLI default Region | Region where the parameter is stored |
| `--show-body` | off | Print the JSON request body before sending |

### Example output

```text
Model: us.amazon.nova-lite-v1:0  (provider: amazon-nova)
Latency header: 642 ms
Tokens: in=18 out=54

RAG retrieves relevant documents from a knowledge source and adds them to the prompt...
```

## Lab exercises

1. Run with `--show-body` and note the Nova request format.
2. Change `modelId` in `model-config.json` to `amazon.titan-text-express-v1`, update the parameter, and rerun. Compare the two request bodies.
3. Try a Nova 2 model with reasoning turned on, using `extraBody`:
   ```json
   "extraBody": { "reasoningConfig": { "type": "enabled", "maxReasoningEffort": "low" } }
   ```
   The reasoning text comes back as `[REDACTED]`, and the script prints only the answer.
4. Rewrite the call with the **Converse** API and compare it with InvokeModel. Converse uses one request format for every model.

## Troubleshooting

| Error | Cause | Fix |
| --- | --- | --- |
| `Unable to locate credentials` | AWS CLI not configured | Run `aws configure` |
| `ParameterNotFound` | Wrong name or Region | Check `--param` and `--ssm-region` |
| `SSM parameter ... has no 'modelId' key` | JSON stored without quotes (Windows quoting) | Store it again using `file://model-config.json` |
| `AccessDeniedException ... INVALID_PAYMENT_INSTRUMENT` | Marketplace subscription failed (AISPL) | Use a Nova or Titan model |
| `AccessDeniedException` (other) | Missing IAM permission or model access | Check the IAM permissions above |
| `ValidationException` | Body fields don't match the model, or the model ID is invalid | Run with `--show-body` and check the model's request format in the Bedrock User Guide |
| `ThrottlingException` | Too many requests | Retry with backoff, or use a cross-Region inference profile |

## Files

```text
invoke_model_ssm.py   # the script
model-config.json     # model settings to store in SSM
README.md             # this file
```
