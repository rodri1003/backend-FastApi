# Backend FastAPI – Fase Inicial

## Descripción

Este proyecto corresponde a la fase inicial del backend del sistema.

Se desarrolló utilizando FastAPI con el objetivo de implementar la autenticación de usuarios y el control de acceso por roles.

Actualmente el sistema permite:

- Registrar usuarios
- Iniciar sesión mediante JWT
- Proteger endpoints
- Diferenciar accesos entre usuarios normales y administradores

Esta implementación funciona como base para continuar desarrollando el sistema completo en fases posteriores.

---

## Tecnologías utilizadas

- Python
- FastAPI
- SQL Server
- SQLAlchemy
- JWT

---

Funcionalidades implementadas

### Registro de usuarios

**Endpoint:**  
`POST /users/register`

Permite crear un nuevo usuario.  
Las contraseñas se almacenan encriptadas y el rol asignado por defecto es `"user"`.

---

### Login

**Endpoint:**  
`POST /auth/login`

Valida las credenciales y genera un token JWT.  
Este token debe enviarse para acceder a endpoints protegidos.

---

### Usuario autenticado

**Endpoint:**  
`GET /users/me`

Devuelve la información del usuario que inició sesión.

---

### Endpoints exclusivos para administrador

- `GET /admin/ping`
- `GET /admin/users`

Estos endpoints solo pueden ser accedidos por usuarios con rol `"admin"`.

Si un usuario con rol `"user"` intenta acceder, el sistema responde con:

`403 Forbidden`

---

## ¿Cómo se asigna un administrador?

Actualmente los administradores se definen directamente desde la base de datos.

El registro crea usuarios con rol `"user"` por defecto.

Para convertir un usuario en administrador se ejecuta en SQL Server:

```sql
UPDATE users
SET role = 'admin'
WHERE username = 'nombre_usuario';
Esta solución es temporal para esta fase del proyecto.


# Cómo ejecutar el proyecto
(En una terminal de VS Code)

Crear entorno virtual:
python -m venv venv

Activarlo (Windows):
venv\Scripts\activate

Instalar dependencias:
pip install -r requirements.txt

Ejecutar el servidor:
uvicorn app.main:app --reload

Acceder a la documentación interactiva:
http://127.0.0.1:8000/docs


# Estado actual
Se completó la implementación de autenticación y control de acceso por roles.
El backend se encuentra listo para continuar con el desarrollo del sistema en las siguientes fases.