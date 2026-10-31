# codeg ACP transcript fixtures (TRAE / ZCode readers)

Both transcripts are **synthetic** (hand-written) but follow the documented
codeg ACP transcript schema v1 (`acp_transcript.rs`, Apache-2.0):

- header line: `{"v":1,"kind":"header","agent":"…","session_id":"…","cwd":"…","started_at_ms":…}`
- entries: `{"t":<ms>,"k":"prompt"|"update"|"turn_end","p":…}` with ACP
  `sessionUpdate` payloads (`agent_message_chunk`, `agent_thought_chunk`,
  `tool_call`, `tool_call_update`).

They are not real TRAE/ZCode sessions and therefore do **not** count as real
coverage; they only validate our reader fallback for
`<codeg-home>/acp-transcripts/<registry-id>/<session-id>.jsonl`.
