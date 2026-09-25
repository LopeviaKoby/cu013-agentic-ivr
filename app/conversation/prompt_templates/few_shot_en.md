# Decision examples

Fixed format for each example: minimal state, caller turn and the expected
structured semantics. Do not copy these sentences; apply the criterion.

<ejemplo>
State: goal RESET_PASSWORD, current step not completed.
Previous assistant turn: "Were you able to open the security information
portal?"
Caller: "yes, I opened it"
Decision: procedure_observation ADVANCE (unambiguous answer to the direct
completion question); keep the goal.
</ejemplo>

<ejemplo>
State: goal RESET_PASSWORD, current step not completed.
Caller: "ok, let's continue with the change"
Decision: procedure_observation NONE (a continuation does not confirm that the
step was completed); answer the current step without advancing.
</ejemplo>

<ejemplo>
State: goal RESET_PASSWORD, current step not completed.
Caller: "where did you say I should go in?"
Decision: procedure_observation NONE (side question: it does not complete the
step nor restart it); repeat the current step instruction.
</ejemplo>