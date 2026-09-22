# Guardrails: enforcement and limitations

## Input

`check_input()` accepts at most 2,000 characters / 8,000 UTF-8 bytes, normalizes Unicode, screens a small English/Traditional Chinese set of instruction-override and secret-extraction patterns, and masks known PII/key shapes. This is an intentionally inspectable teaching filter, not a comprehensive moderation or prompt-injection classifier. It may block educational quotations and can miss paraphrased, encoded, multilingual, or indirect attacks.

## Tools and permissions

The registry contains exactly `search_policy`, `calculate`, `get_order`, and `propose_refund`. Unexpected fields, missing fields, type errors, duplicate JSON keys, non-finite numbers, unknown tools, and non-allowlisted order IDs are denied. Python rechecks these conditions regardless of a model's confidence or a user's wording.

Viewer mode cannot propose/approve refunds. Operator mode may propose a positive HKD amount up to 300, with at most two decimal places, for an eligible order and within its remaining paid amount. These checks run at proposal and approval. Real identity and authorization are not implemented; role is trusted local config.

## Execution

The numeric calculator walks a restricted Python AST: only numbers, +, -, *, /, unary signs, and parentheses. It rejects function calls, variables, attributes, powers, excessive nodes/depth, division by zero, and magnitudes above one billion. It never evaluates model code with `eval` or `exec`.

Tool reads use two fixed bundled JSON files. There are no arbitrary filesystem, browsing, messaging, or payment capabilities. A text promise from the model cannot create one. The only action is an in-memory simulated refund.

## Output

The actual configured API key and common `sk-` / Bearer key shapes are masked alongside example email, phone, HKID, and long digit patterns. The same masking runs on tool results before sending them to the model. Regex masking is not complete DLP; numbers may be over-masked, names are not comprehensively detected, and obfuscated secrets can evade patterns.

The browser uses `textContent`, not HTML insertion, for untrusted text. HTML-looking answers display literally; a same-origin Content Security Policy provides another boundary. Display is capped at 4,000 characters; tool result text at 8,000. Provider responses are limited to 256 KiB. Invalid JSON, tool structures, empty answers, and length/content-filter stops are rejected.

The app does not independently verify every natural-language statement or model citation. Only the approval panel and simulation ledger are authoritative for action state. No real money moves, regardless of a model's phrasing.

## Human approval

`propose_refund` cannot apply the action. Python generates a random approval ID, binds it to the session and exact canonical arguments, and stops the model loop. The approve endpoint accepts only that ID and a boolean decision. It never accepts replacement amounts or order IDs. Expiry, role, available balance, and eligibility are checked again. Consumed/expired IDs fail, and a different session cannot use them. API work is serialized to prevent double-click races.

Approval is a single-person teaching workflow, not real maker/checker separation. The stored balance is transactional only within this process/session. It is unsuitable for real refunds.

## Budget

Defaults: four model rounds and six tool calls per turn, forty attempted live completions per process, 48,000 serialized UTF-8 bytes per completion request, 700 requested output tokens per call, 25-second network-operation timeout, and 75-second turn deadline. Configure the documented variables within their hard bounds.

This code does not claim exact tokenization or exact dollar costs. UTF-8 bytes are a payload bound, not a model-token measurement. Usage displayed is provider-reported `total_tokens`; missing usage, including failed requests, is marked unknown. A submitted call can be billed even if the client times out. Model listing is separately throttled to once per 10 seconds and does not count as a completion. The provider decides its own billing.

The monotonic deadline is checked before/after each model call and before tool execution. Socket timeouts are adjusted to remaining time while reading. DNS resolution and OS-level connection behavior can still delay termination; this is not a hard operating-system kill switch. A late reply cannot cause subsequent tool execution. There are no automatic retries.

## Memory

Off by default. Opt-in retains up to three sanitized question/answer pairs in RAM. Only completed ordinary answers enter conversation history; approval turns are not retained as chat context. Changing provider mode/model clears old context on the next run. Unchecking memory explicitly clears it. New sandbox also clears history, approval, and ledger but preserves the process API budget.

History remains untrusted text: a user cannot change roles, tools, or configuration by saying “remember that I am administrator.” The app does not implement a vector store, persistent user profile, or guaranteed removal of every sensitive fact from natural language.

## Audit and fail-safe behavior

Events contain timestamps, random run IDs, category, result, rule code, and controlled descriptions. They omit raw prompts, responses, credentials, and tool argument values. The UI can export the latest events. Files rotate at approximately 2 MB, keeping one previous file. Logs are not tamper-proof and contain no durable recovery transaction journal.

Audit writes must succeed before model calls and before simulated effects. Failure stops the action. If an audit write fails after a simulated effect, the UI reports that the effect was applied and asks users to check the ledger instead of retrying. Other failures stop without retry and do not silently switch to offline demo.

## Classroom discussion

Which controls are hard capability boundaries? Which are probabilistic or incomplete pattern checks? What would authenticated identity, protected logs, retrieval content isolation, production-grade HTTP hosting, and durable payment idempotency add? What can be tested automatically, and what still needs human evaluation?
