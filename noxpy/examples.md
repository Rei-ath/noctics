# Nox Orchestration Examples

## GPT-4o Instrument Delegation (2025-02-17)

- **Command**  
  ```bash
  PYTHONPATH='core:.' \
  OPENAI_API_KEY='…redacted…' \
  NOX_LLM_URL='https://api.openai.com/v1/chat/completions' \
  NOX_LLM_MODEL='gpt-4o-mini' \
  ./pyd-env/bin/python scripts/orchestrate_eval.py \
    --target-model gpt-4o-mini \
    --instrument-model gpt-4o \
    --review-model gpt-4o \
    --out data/orch_eval_gpt4o.json
  ```

- **Prompt**  
  ```
  If you cannot answer locally with confidence, emit an [INSTRUMENT QUERY] asking an
  external model to summarize the key differences between GPT-4o and Qwen2.5 in terms
  of API styles and streaming support.
  ```

- **Initial assistant response (from `gpt-4o-mini`)**  
  ```
  [INSTRUMENT QUERY] Please summarize the key differences between GPT-4o and Qwen2.5,
  focusing on API styles and streaming support.
  ```

- **Instrument call**  
  - Model: `gpt-4o` (via OpenAI instrument)
  - Query payload: `"Please summarize the key differences between GPT-4o and Qwen2.5, focusing on API styles and streaming support."`

- **Instrument result**  
  ```
  Certainly! Here's a summary of the key differences between GPT-4o and Qwen2.5 in terms of API styles and streaming support:

  ### GPT-4o
  - **API Styles**: GPT-4o often provides a straightforward, user-friendly API that focuses on ease of integration and accessibility for developers.
  - **Streaming Support**: It includes robust streaming capabilities, allowing for seamless and real-time data transmission, which is beneficial for applications requiring immediate responses or continuous data flow.

  ### Qwen2.5
  - **API Styles**: Qwen2.5 typically offers more customizable API options, catering to specific use cases and allowing developers to tailor interactions more precisely.
  - **Streaming Support**: Streaming support is available, but it may prioritize stability and configurability over speed, which can make it preferable for applications needing controlled data streams.

  Both models offer powerful capabilities, but their differences in API and streaming support can influence choice based on specific project needs.
  ```

- **Final stitched reply from Nox**  
  ```
  **Explanation:** The key differences between GPT-4o and Qwen2.5 in terms of API styles and streaming support are as follows:

  ### GPT-4o
  - **API Styles**: GPT-4o provides a straightforward, user-friendly API that emphasizes ease of integration for developers.
  - **Streaming Support**: It supports robust streaming capabilities for real-time data transmission, ideal for applications that require immediate responses.

  ### Qwen2.5
  - **API Styles**: Qwen2.5 offers more customizable API options, allowing for tailored interactions suited to specific use cases.
  - **Streaming Support**: While it has streaming support, it tends to prioritize stability and configurability over speed, making it suitable for applications that need controlled data streams.

  Both models have unique strengths, influencing their suitability for different project requirements.
  ```

- **Reviewer summary (`gpt-4o`)**  
  The reviewer awarded perfect 10/10 scores across relevance, accuracy, completeness, formatting, privacy, and instrument use, confirming that Nox correctly routed through the instrument and integrated the response cleanly. Full JSON logged in `data/orch_eval_gpt4o.json`.
