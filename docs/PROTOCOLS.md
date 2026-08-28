# IT-Support Protocols & Business Rules

Enterprise IT Operational Procedures (IOPs) define the authoritative truth for diagnostic steps and actions.

## Milestone Protocols

1. **VPN Troubleshooting (Milestone 1 target)**:
   - Diagnostic criteria: user location (Peru / Chile / Colombia / Brazil), VPN client (FortiClient / Cisco AnyConnect / GlobalProtect), internet connectivity status, specific error messages.
   - Clarification handling: explaining technical terms (gateway, client, port) without losing conversational context.
   - Correction handling: caller updates previously stated facts without restarting the protocol.

2. **Password Reset (Future scope)**:
   - Requires employee identity verification before triggering directory password update.

3. **Account Unlock (Future scope)**:
   - Unlocking domain accounts following identity validation.

> **Rule**: In Increment 1, protocols are specified declaratively in `evals/golden/`. Full execution logic will be introduced in subsequent increments.
