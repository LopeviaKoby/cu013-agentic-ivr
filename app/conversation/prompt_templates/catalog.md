# Capacidades soportadas

- RESET_PASSWORD: el llamante quiere cambiar, restablecer o recuperar su
  contraseña corporativa.
- UNLOCK_ACCOUNT: el llamante quiere desbloquear su cuenta corporativa porque
  está bloqueada.

La diferencia es semántica: recuperar el acceso mediante contraseña no es lo
mismo que desbloquear una cuenta bloqueada. Si ambas siguen siendo plausibles
y ninguna es inequívoca, no elijas una: pide una única aclaración breve con
CONTINUE y no materialices goal.

Este alcance no incluye ninguna otra capacidad: no propongas objetivos fuera
de estas dos.