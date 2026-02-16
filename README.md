Backend FastAPI – Fase Inicial

Descripción

Este proyecto corresponde a la fase inicial del backend del sistema.

Se desarrolló utilizando FastAPI con el objetivo de implementar la autenticación de usuarios y el control de acceso por roles.
Actualmente el sistema permite registrar usuarios, iniciar sesión mediante JWT, proteger endpoints y diferenciar accesos entre usuarios normales y administradores.
Esta implementación funciona como base para continuar desarrollando el sistema completo en fases posteriores.

Tecnologías utilizadas:
- Python
- FastAPI
- SQL Server
- SQLAlchemy
- JWT

Funcionalidades implementadas:

- Registro de usuarios:
Permite crear un nuevo usuario. Las contraseñas se almacenan encriptadas y el rol asignado por defecto es "user".

- Login:
Valida las credenciales y genera un token JWT. Este token debe enviarse para acceder a endpoints protegidos.

- Usuario autenticado:
Devuelve la información del usuario que inició sesión.

- Endpoints exclusivos para administrador:
Solo pueden ser accedidos por usuarios con rol "admin". Si un usuario con rol "user" intenta acceder, el sistema responde con error 403 Forbidden.

- Asignación de administrador:
Actualmente los administradores se definen directamente desde la base de datos.
El registro crea usuarios con rol "user" por defecto.

- Para convertir un usuario en administrador se debe actualizar su rol en la base de datos a "admin".
Esta solución es temporal para esta fase del proyecto.


Cómo ejecutar el proyecto:
(en una terminal de vs code)

-Crear entorno virtual con python: -m venv venv

-Activarlo con: venv\Scripts\activate

-Instalar dependencias con: pip install -r requirements.txt

-Ejecutar el servidor con: uvicorn app.main:app --reload

-Acceder a la documentación interactiva en: http://127.0.0.1:8000/docs


Estado actual:
Se completó la implementación de autenticación con JWT, registro de usuarios y control de acceso por roles.
El backend se encuentra listo para continuar con el desarrollo del sistema en las siguientes fases.
