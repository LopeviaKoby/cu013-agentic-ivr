# XCALLY / Cally Square Integration Contract

## Telephony Media Path

The media path is sequential and discrete (half-duplex turn-taking):

```
Caller speaks
  ──> XCALLY / Cally Square captures audio
  ──> Google Speech-to-Text (ASR) produces final transcript
  ──> HTTP POST /turn to Backend
  ──> Backend processes and returns text response
  ──> Google Text-to-Speech (TTS) synthesizes audio
  ──> XCALLY plays audio to Caller
  ──> Caller listens and responds
```

> **Note**: Do not assume full-duplex audio, streaming barge-in, or open WebRTC connections. Each turn is an isolated HTTP request.

## HTTP Endpoints

### 1. Health Check
- **Method**: `GET /health`
- **Response**: `200 OK`
```json
{
  "status": "ok",
  "version": "0.2.0"
}
```

### 2. Conversational Turn
- **Method**: `POST /turn`
- **Request Body**:
```json
{
  "conversation_id": "Ivr02-20260828-123456",
  "text": "Estoy en Perú y uso FortiClient"
}
```
- **Validation**:
  - `conversation_id`: Non-empty, non-whitespace string.
  - `text`: Non-empty, non-whitespace string.

- **Response Body**: `200 OK`
```json
{
  "turn_id": "turn-a1b2c3d4e5f6",
  "route": "CONTINUE",
  "text": "Entendido. ¿En qué más puedo ayudarte?"
}
```

### Routing Values
- `CONTINUE`: Keep dialogue open; Cally Square gathers next utterance.
- `COLLECT_IDENTITY`: Prompt caller for identity verification (DNI / employee code).
- `COMPLETE`: Issue resolved; terminate call gracefully.
- `ESCALATE`: Issue cannot be resolved autonomously; transfer to human agent.
