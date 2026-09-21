import os
import random
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from bson import ObjectId
from datetime import datetime, timezone

from clusterdex import CATALOGO_CLUSTERMONES, PROBABILIDADES, COSTO_TIRADA

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
        "usuario": datos.username,
        "contraseña": datos.password,
        "monedas": 100,            # Monedas de bienvenida
        "ultimo_reclamo": None      # Control de cooldown
    }
    
    # 3. Inserción asíncrona en Atlas
    resultado = await coleccion_usuarios.insert_one(nuevo_usuario)
    
    return {
        "mensaje": "Usuario registrado con éxito",
        "id": str(resultado.inserted_id),
        "usuario": datos.username,
        "monedas": 100
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
        "usuario": usuario.get("usuario"),
        "monedas": usuario.get("monedas", 0),
        "ultimo_reclamo": usuario.get("ultimo_reclamo")
    }

COOLDOWN_RECLAMO_SEGUNDOS = 60
RECOMPENSA_MONEDAS = 50

@app.post("/usuarios/{id}/reclamar")
async def reclamar_monedas(id: str):
    if not ObjectId.is_valid(id):
        raise HTTPException(status_code=400, detail="Formato de ID inválido.")

    coleccion_usuarios = app.state.usuarios
    usuario = await coleccion_usuarios.find_one({"_id": ObjectId(id)})

    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado.")

    ahora = datetime.now(timezone.utc)
    ultimo_reclamo = usuario.get("ultimo_reclamo")

    if ultimo_reclamo:
        if ultimo_reclamo.tzinfo is None:
            ultimo_reclamo = ultimo_reclamo.replace(tzinfo=timezone.utc)
            
        segundos_pasados = (ahora - ultimo_reclamo).total_seconds()
        
        if segundos_pasados < COOLDOWN_RECLAMO_SEGUNDOS:
            segundos_restantes = int(COOLDOWN_RECLAMO_SEGUNDOS - segundos_pasados)
            horas_restantes = segundos_restantes // 3600
            minutos_restantes = (segundos_restantes % 3600) // 60
            raise HTTPException(
                status_code=400,
                detail=f"Recompensa diaria no disponible. Espera {horas_restantes}h {minutos_restantes}m."
            )

    await coleccion_usuarios.update_one(
        {"_id": ObjectId(id)},
        {
            "$inc": {"monedas": RECOMPENSA_MONEDAS},
            "$set": {"ultimo_reclamo": ahora}
        }
    )

    nuevo_balance = usuario.get("monedas", 0) + RECOMPENSA_MONEDAS

    return {
        "mensaje": f"Reclamaste tu recompensa diaria de {RECOMPENSA_MONEDAS} monedas",
        "monedas_actuales": nuevo_balance
    }

@app.get("/clustermones/clusterdex")
async def obtener_clusterdex():
    total_especies = sum(len(especies) for especies in CATALOGO_CLUSTERMONES.values())
    return {
        "total_especies_existentes": total_especies,
        "clusterdex": CATALOGO_CLUSTERMONES,
        "probabilidades": PROBABILIDADES,
        "costo_tirada": COSTO_TIRADA
    }

@app.get("/clustermones/{usuario_id}")
async def listar_clustermones_usuario(usuario_id: str):
    # 1. Validar formato del ObjectId
    if not ObjectId.is_valid(usuario_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de ID inválido."
        )

    # 2. Verificar que el usuario exista en Atlas
    coleccion_usuarios = app.state.usuarios
    usuario = await coleccion_usuarios.find_one({"_id": ObjectId(usuario_id)})
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado."
        )

    # 3. Buscar todas las criaturas asociadas a ese usuario
    coleccion_clustermones = app.state.clustermones
    cursor = coleccion_clustermones.find({"usuario_id": ObjectId(usuario_id)})
    
    # 4. Formatear la lista para devolver JSON limpio
    clustermones = []
    async for c in cursor:
        clustermones.append({
            "id": str(c["_id"]),
            "usuario_id": str(c["usuario_id"]),
            "nombre": c.get("nombre"),
            "rareza": c.get("rareza"),
            # "nivel": c.get("nivel", 1),
            # "ataque": c.get("ataque"),
            # "defensa": c.get("defensa")
        })

    return {
        "admin": usuario.get("usuario"),
        "total_clustermones": len(clustermones),
        "clustermones": clustermones
    }

# ---------------------------------------------------------
# CATÁLOGO Y CONFIGURACIÓN DEL SISTEMA GACHA
# ---------------------------------------------------------

class TiradaRequest(BaseModel):
    usuario_id: str

# ---------------------------------------------------------
# ENDPOINT: INVOCACIÓN / TIRADA ALEATORIA
# ---------------------------------------------------------
@app.post("/clustermones/tirada")
async def realizar_tirada(datos: TiradaRequest):
    usuario_id = datos.usuario_id

    # 1. Validar formato de ID
    if not ObjectId.is_valid(usuario_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de ID inválido."
        )

    coleccion_usuarios = app.state.usuarios
    usuario = await coleccion_usuarios.find_one({"_id": ObjectId(usuario_id)})

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado."
        )

    # 2. Validar saldo suficiente
    saldo_actual = usuario.get("monedas", 0)
    if saldo_actual < COSTO_TIRADA:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Monedas insuficientes. Tienes {saldo_actual} y la tirada cuesta {COSTO_TIRADA}."
        )

    # 3. Descontar las monedas en la base de datos
    await coleccion_usuarios.update_one(
        {"_id": ObjectId(usuario_id)},
        {"$inc": {"monedas": -COSTO_TIRADA}}
    )

    # 4. Sorteo ponderado de rareza y selección de especie
    rarezas = list(PROBABILIDADES.keys())
    pesos = list(PROBABILIDADES.values())

    rareza_obtenida = random.choices(rarezas, weights=pesos, k=1)[0]
    nombre_obtenido = random.choice(CATALOGO_CLUSTERMONES[rareza_obtenida])

    # 5. Guardar la nueva criatura vinculada al usuario
    nuevo_clustermon = {
        "usuario_id": ObjectId(usuario_id),
        "nombre": nombre_obtenido,
        "rareza": rareza_obtenida
    }

    coleccion_clustermones = app.state.clustermones
    resultado = await coleccion_clustermones.insert_one(nuevo_clustermon)

    saldo_restante = saldo_actual - COSTO_TIRADA

    mensaje = (
        f"¡INCREÍBLE! ¡Obtuviste una criatura LEGENDARIA: {nombre_obtenido}!"
        if rareza_obtenida == "Legendario"
        else f"¡Invocación exitosa! Obtuviste un {nombre_obtenido} ({rareza_obtenida})."
    )

    return {
        "mensaje": mensaje,
        "clustermon": {
            "id": str(resultado.inserted_id),
            "nombre": nombre_obtenido,
            "rareza": rareza_obtenida
        },
        "monedas_restantes": saldo_restante
    }