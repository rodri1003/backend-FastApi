# 🏨 AFE Resort & Spa — Backend FastAPI

> **API REST del Sistema de Gestión Hotelera y Experiencia de Huéspedes**
>
> Desarrollado con FastAPI y SQL Server, enfocado en un sistema de autenticación JWT robusto, control de accesos basado en roles (RBAC) con Casbin, auditoría y un motor financiero de facturación electrónica.

---

## 🛠️ Tecnologías Utilizadas

- **Python 3.11**
- **FastAPI** (Framework web asíncrono de alto rendimiento)
- **Microsoft SQL Server** (Motor de base de datos relacional)
- **SQLAlchemy 2.0** (ORM de base de datos)
- **Alembic** (Gestor de migraciones de base de datos)
- **Casbin** (Control de acceso basado en roles - RBAC)
- **JWT** (Autenticación mediante tokens web JSON)

---

## 🚀 Instalación y Ejecución con Docker (Recomendado)

Docker Compose te permite levantar la base de datos SQL Server, el backend y el frontend con un solo comando, configurando y sembrando la base de datos automáticamente.

### Requisitos Previos
- Tener instalado **Docker Desktop** (o Docker Engine) y tenerlo en ejecución.
- **Configurar el archivo de entorno (`.env`)**:
  Por seguridad, las claves de Cloudinary, SendGrid (SMTP) y pasarelas de pago no se suben a Git. 
  1. Copia el archivo `.env.example` y renómbralo como `.env` en la carpeta `backend-FastApi`.
  2. Llena las credenciales correspondientes.

---

### Caso de Uso A: Levantar Todo el Entorno (Base de Datos + Backend + Frontend)
Si vas a trabajar en ambos lados o deseas probar la integración completa del sistema:

1. Asegúrate de tener los repositorios `backend-FastApi` y `proyecto-frontend` clonados en la misma carpeta padre (lado a lado).
2. Abre tu terminal en la carpeta del backend `backend-FastApi`.
3. Ejecuta el siguiente comando para compilar e iniciar todos los servicios:
   ```bash
   docker compose up --build
   ```
4. **¿Qué sucede automáticamente?**
   - Se creará una base de datos limpia de SQL Server.
   - Se creará la base de datos `ProyectoAFE_RBAC`.
   - Se ejecutarán las migraciones de Alembic para estructurar las tablas.
   - Se ejecutarán los scripts SQL de semilla de datos que dejes en la carpeta `db_seed/`.
   - El backend estará disponible en: [http://localhost:8000](http://localhost:8000)
   - El frontend estará disponible en: [http://localhost:5173](http://localhost:5173)

---

### Caso de Uso B: Levantar Solo Backend y Base de Datos (Desarrollador Backend)
Si solo vas a trabajar en los endpoints de la API y no necesitas tener la interfaz visual corriendo:

1. Abre tu terminal en la carpeta `backend-FastApi`.
2. Levanta únicamente los contenedores de base de datos y backend con:
   ```bash
   docker compose up db backend --build
   ```
3. Podrás interactuar y probar todas tus APIs desde la documentación interactiva Swagger:
   - **Swagger Docs**: [http://localhost:8000/docs](http://localhost:8000/docs)
   - **Redoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
4. También puedes conectarte directamente a la base de datos desde SQL Server Management Studio (SSMS) usando:
   - **Server**: `localhost,1433`
   - **User**: `sa`
   - **Password**: `SomeSecurePassword123!`

---

### 🗄️ Carga de Datos y Backups Automáticos
El contenedor cuenta con un mecanismo que importa automáticamente registros al levantar:

1. Si deseas precargar la base de datos con tus datos de desarrollo actuales, exporta un script desde tu SSMS haciendo clic derecho en tu base de datos -> **Tasks** -> **Generate Scripts...**
2. En la configuración avanzada del script, marca **"Types of data to script: Data only"** (para evitar conflictos de esquema con Alembic).
3. Guarda el archivo `.sql` resultante en el directorio:
   `backend-FastApi/db_seed/`
4. Al correr `docker compose up`, el contenedor importará y ejecutará este script inmediatamente después de aplicar las migraciones, y luego lo renombrará a `.sql.imported` para no volver a correrlo.

---

### 💾 Persistencia de Datos
Los datos del contenedor de SQL Server se guardan de forma persistente en un volumen de Docker llamado `sql_data`. Tu información no se perderá al apagar los contenedores.
Si por alguna razón necesitas reiniciar la base de datos por completo a su estado limpio original, ejecuta:
```bash
docker compose down -v
```

---

## 🐍 Ejecución Local Tradicional (Sin Docker)

Si prefieres ejecutar el backend en tu entorno local físico sin contenedores:

### 1. Requisitos
- Python 3.11 instalado en tu máquina.
- Una instancia local de Microsoft SQL Server (como SQL Server Express `localhost\SQLEXPRESS`).

### 2. Crear y activar el entorno virtual
```bash
python -m venv venv
```
- **En Windows (PowerShell)**:
  ```bash
  .\venv\Scripts\Activate.ps1
  ```
- **En Mac/Linux**:
  ```bash
  source venv/bin/activate
  ```

### 3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 4. Configurar el archivo `.env`
Crea o edita tu archivo `.env` en la raíz de `backend-FastApi` con tus credenciales de base de datos locales:
```env
DB_SERVER=localhost\SQLEXPRESS
DB_NAME=ProyectoAFE_RBAC
DB_TRUSTED_CONNECTION=yes
JWT_SECRET_KEY=tu_clave_secreta_jwt
```

### 5. Ejecutar migraciones de Alembic
```bash
alembic upgrade head
```

### 6. Iniciar el servidor
```bash
uvicorn app.main:app --reload
```
Accede a la documentación en: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
