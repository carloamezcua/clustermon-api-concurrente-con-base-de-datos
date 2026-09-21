import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from bson import ObjectId

# 1. Cargar las variables desde el archivo .env
load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI")
if not MONGODB_URI:
    raise RuntimeError("La variable MONGODB_URI no está definida en el archivo .env")

DATABASE_NAME = os.getenv("DATABASE_NAME", "ClustermonDB")

COLL_USUARIOS = os.getenv("COLL_USUARIOS", "usuarios")
COLL_CLUSTERMONES = os.getenv("COLL_CLUSTERMONES", "clustermones")

# 2. Gestor de ciclo de vida (Lifespan)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # STARTUP: abre la conexión al clúster
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DATABASE_NAME]

    # Asignamos las colecciones usando los nombres de las variables de entorno
    app.state.usuarios = db[COLL_USUARIOS]
    app.state.clustermones = db[COLL_CLUSTERMONES]

    print("Conexión exitosa a MongoDB Atlas.")

    yield

    # SHUTDOWN: cierra la conexión
    client.close()
    print("Conexión con MongoDB cerrada.")

# 3. Inicialización de la aplicación FastAPI
app = FastAPI(
    title="Clustermon API",
    lifespan=lifespan
)

# -------------------------------------------------------------
# MODELOS PYDANTIC
# -------------------------------------------------------------
class UsuarioRegistro(BaseModel):
    username: str = Field(..., min_length=3, max_length=20, description="Nombre de usuario")
    password: str = Field(..., min_length=4, max_length=50, description="Contraseña")

# -------------------------------------------------------------
# ENDPOINTS
# -------------------------------------------------------------
@app.get("/ping")
async def ping():
    return {"status": "ok", "mensaje": "Servidor funcionando"}

@app.post("/usuarios", status_code=status.HTTP_201_CREATED)
async def registrar_usuario(datos: UsuarioRegistro):
    coleccion_usuarios = app.state.usuarios
    
    # 1. Validar que el nombre de usuario no esté repetido
    usuario_existente = await coleccion_usuarios.find_one({"username": datos.username})
    if usuario_existente:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El nombre de usuario ya está en uso."
        )
    
    # 2. Estructura del nuevo entrenador
    nuevo_usuario = {
        "username": datos.username,
        "password": datos.password,
        "coins": 100,            # Monedas de bienvenida
        "last_claim": None      # Control de cooldown
    }
    
    # 3. Inserción asíncrona en Atlas
    resultado = await coleccion_usuarios.insert_one(nuevo_usuario)
    
    return {
        "mensaje": "Usuario registrado con éxito",
        "id": str(resultado.inserted_id),
        "username": datos.username,
        "coins": 100
    }

@app.get("/usuarios/{id}")
async def obtener_usuario(id: str):
    # 1. Validar que la cadena tenga formato de ObjectId
    if not ObjectId.is_valid(id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de ID inválido."
        )

    coleccion_usuarios = app.state.usuarios
    
    # 2. Buscar al entrenador en Atlas
    usuario = await coleccion_usuarios.find_one({"_id": ObjectId(id)})
    
    # 3. Validar si existe
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado."
        )

    # 4. Retornar los datos del perfil (sin exponer la contraseña)
    return {
        "id": str(usuario["_id"]),
        "username": usuario.get("username"),
        "coins": usuario.get("coins", 0),
        "last_claim": usuario.get("last_claim")
    }