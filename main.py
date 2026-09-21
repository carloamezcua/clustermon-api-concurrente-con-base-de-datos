import os
import random
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
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

@app.post("/usuarios/{usuario_id}/reclamar")
async def reclamar_monedas(usuario_id: str):
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
            detail="El usuario no existe."
        )

    # Obtenemos la hora actual en UTC consciente de zona horaria
    ahora = datetime.now(timezone.utc)
    ultimo_reclamo = usuario.get("ultimo_reclamo")

    if ultimo_reclamo:
        # Aseguramos que la fecha leída de Atlas tenga zona UTC
        if ultimo_reclamo.tzinfo is None:
            ultimo_reclamo = ultimo_reclamo.replace(tzinfo=timezone.utc)

        tiempo_transcurrido = (ahora - ultimo_reclamo).total_seconds()

        if tiempo_transcurrido < COOLDOWN_RECLAMO_SEGUNDOS:
            segundos_restantes = int(COOLDOWN_RECLAMO_SEGUNDOS - tiempo_transcurrido)
            
            # Formato legible: muestra segundos si falta menos de 1 minuto
            if segundos_restantes < 60:
                tiempo_str = f"{segundos_restantes}s"
            else:
                m = segundos_restantes // 60
                s = segundos_restantes % 60
                tiempo_str = f"{m}m {s}s"

            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Recompensa no disponible. Espera {tiempo_str}."
            )

    # Si pasó la validación, actualizamos saldo y la fecha del reclamo
    await coleccion_usuarios.update_one(
        {"_id": ObjectId(usuario_id)},
        {
            "$inc": {"monedas": RECOMPENSA_MONEDAS},
            "$set": {"ultimo_reclamo": ahora}
        }
    )

    return {
        "mensaje": f"¡Has reclamado {RECOMPENSA_MONEDAS} monedas con éxito!",
        "monedas_actuales": usuario.get("monedas", 0) + RECOMPENSA_MONEDAS
    }

@app.get("/usuarios/{usuario_id}")
async def obtener_usuario(usuario_id: str):
    if not ObjectId.is_valid(usuario_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de ID inválido."
        )

    usuario = await app.state.usuarios.find_one({"_id": ObjectId(usuario_id)})
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado."
        )

    return {
        "id": str(usuario["_id"]),
        "usuario": usuario.get("usuario"),
        "monedas": usuario.get("monedas", 0)
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
            "nivel": c.get("nivel", 1),
            # "ataque": c.get("ataque"),
            # "defensa": c.get("defensa")
        })

    return {
        "admin": usuario.get("usuario"),
        "total_clustermones": len(clustermones),
        "clustermones": clustermones
    }

@app.post("/clustermones/tirada/{usuario_id}")
async def realizar_tirada(usuario_id: str):

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

    # 5. Guardar la nueva criatura vinculada al usuario (con nivel inicial 1)
    nuevo_clustermon = {
        "usuario_id": ObjectId(usuario_id),
        "nombre": nombre_obtenido,
        "rareza": rareza_obtenida,
        "nivel": 1
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
            "rareza": rareza_obtenida,
            "nivel": 1
        },
        "monedas_restantes": saldo_restante
    }

class LiberarRequest(BaseModel):
    usuario_id: str

RECOMPENSA_LIBERACION = 20

@app.delete("/clustermones/{id}/usuario/{usuario_id}")
async def liberar_clustermon(id: str, usuario_id: str):
    # 1. Validar que ambos sean formatos válidos de ObjectId
    if not ObjectId.is_valid(id) or not ObjectId.is_valid(usuario_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de ID inválido."
        )

    coleccion_usuarios = app.state.usuarios
    coleccion_clustermones = app.state.clustermones

    # 2. Validar que el usuario exista
    usuario = await coleccion_usuarios.find_one({"_id": ObjectId(usuario_id)})
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario no existe."
        )

    # 3. Validar que la criatura exista
    clustermon = await coleccion_clustermones.find_one({"_id": ObjectId(id)})
    if not clustermon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El Clustermon no existe."
        )

    # 4. Validar que la criatura realmente le pertenezca a ese usuario
    if clustermon.get("usuario_id") != ObjectId(usuario_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este Clustermon no te pertenece. No puedes liberarlo."
        )

    # 5. Borrar criatura y abonar recompensa
    await coleccion_clustermones.delete_one({"_id": ObjectId(id)})
    await coleccion_usuarios.update_one(
        {"_id": ObjectId(usuario_id)},
        {"$inc": {"monedas": RECOMPENSA_LIBERACION}}
    )

    return {
        "mensaje": f"Has liberado a {clustermon.get('nombre')}. Recibiste {RECOMPENSA_LIBERACION} monedas.",
        "clustermon_liberado_id": id
    }

COSTO_BASE = 20
FACTOR_EXPONENCIAL = 1.07

@app.post("/clustermones/{id}/subir-nivel/{usuario_id}")
async def subir_nivel_clustermon(id: str, usuario_id: str):
    # 1. Validar formato de IDs
    if not ObjectId.is_valid(id) or not ObjectId.is_valid(usuario_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato de ID inválido."
        )

    coleccion_usuarios = app.state.usuarios
    coleccion_clustermones = app.state.clustermones

    # 2. Validar que el usuario exista
    usuario = await coleccion_usuarios.find_one({"_id": ObjectId(usuario_id)})
    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario no existe."
        )

    # 3. Validar que la criatura exista
    clustermon = await coleccion_clustermones.find_one({"_id": ObjectId(id)})
    if not clustermon:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El Clustermon no existe."
        )

    # 4. Validar pertenencia
    if clustermon.get("usuario_id") != ObjectId(usuario_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este Clustermon no te pertenece. No puedes subirlo de nivel."
        )

    # 5. Cálculo dinámico del costo exponencial
    nivel_actual = clustermon.get("nivel", 1)
    costo_subida = round(COSTO_BASE * (FACTOR_EXPONENCIAL ** (nivel_actual - 1)))

    # 6. Validar saldo de monedas
    saldo_actual = usuario.get("monedas", 0)
    if saldo_actual < costo_subida:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Monedas insuficientes. Subir a nivel {nivel_actual + 1} cuesta "
                f"{costo_subida} monedas y tienes {saldo_actual}."
            )
        )

    # 7. Cobrar monedas
    await coleccion_usuarios.update_one(
        {"_id": ObjectId(usuario_id)},
        {"$inc": {"monedas": -costo_subida}}
    )

    # 8. Incrementar el nivel en Atlas
    criatura_actualizada = await coleccion_clustermones.find_one_and_update(
        {"_id": ObjectId(id)},
        {"$inc": {"nivel": 1}},
        return_document=True
    )

    siguiente_nivel = criatura_actualizada.get("nivel", 1)
    siguiente_costo = round(COSTO_BASE * (FACTOR_EXPONENCIAL ** (siguiente_nivel - 1)))

    return {
        "mensaje": f"¡Tu {clustermon.get('nombre')} subió a nivel {siguiente_nivel}!",
        "clustermon_id": id,
        "nuevo_nivel": siguiente_nivel,
        "monedas_gastadas": costo_subida,
        "monedas_restantes": saldo_actual - costo_subida,
        "costo_siguiente_nivel": siguiente_costo
    }

@app.post("/clustermones/intercambiar/{usuario1_id}/{clustermon1_id}/{usuario2_id}/{clustermon2_id}")
async def intercambiar_clustermones(
    usuario1_id: str, 
    clustermon1_id: str, 
    usuario2_id: str, 
    clustermon2_id: str
):
    # 1. Validar formato de los cuatro identificadores
    ids = [usuario1_id, clustermon1_id, usuario2_id, clustermon2_id]
    if not all(ObjectId.is_valid(x) for x in ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uno o más IDs tienen un formato inválido."
        )

    if usuario1_id == usuario2_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un usuario no puede intercambiar consigo mismo."
        )

    if clustermon1_id == clustermon2_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se puede intercambiar la misma criatura dos veces."
        )

    coleccion_usuarios = app.state.usuarios
    coleccion_clustermones = app.state.clustermones

    # 2. Validar que ambos jugadores existan en Atlas
    u1 = await coleccion_usuarios.find_one({"_id": ObjectId(usuario1_id)})
    u2 = await coleccion_usuarios.find_one({"_id": ObjectId(usuario2_id)})

    if not u1 or not u2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Uno o ambos usuarios no existen."
        )

    # 3. Validar que la criatura 1 exista y sea de u1
    c1 = await coleccion_clustermones.find_one({"_id": ObjectId(clustermon1_id)})
    if not c1:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"La criatura con ID {clustermon1_id} no existe."
        )
    if c1.get("usuario_id") != ObjectId(usuario1_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"La criatura {c1.get('nombre')} no le pertenece a {u1.get('usuario')}."
        )

    # 4. Validar que la criatura 2 exista y sea de u2
    c2 = await coleccion_clustermones.find_one({"_id": ObjectId(clustermon2_id)})
    if not c2:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"La criatura con ID {clustermon2_id} no existe."
        )
    if c2.get("usuario_id") != ObjectId(usuario2_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"La criatura {c2.get('nombre')} no le pertenece a {u2.get('username')}."
        )

    # 5. Ejecutar el cruce de dueños en Atlas (Referencias Manuales)
    await coleccion_clustermones.update_one(
        {"_id": ObjectId(clustermon1_id)},
        {"$set": {"usuario_id": ObjectId(usuario2_id)}}
    )
    await coleccion_clustermones.update_one(
        {"_id": ObjectId(clustermon2_id)},
        {"$set": {"usuario_id": ObjectId(usuario1_id)}}
    )

    return {
        "mensaje": f"¡Intercambio completado con éxito!",
        "detalles": {
            f"{u1.get('usuario')} recibió": {
                "id": clustermon2_id,
                "nombre": c2.get("nombre"),
                "nivel": c2.get("nivel", 1)
            },
            f"{u2.get('usuario')} recibió": {
                "id": clustermon1_id,
                "nombre": c1.get("nombre"),
                "nivel": c1.get("nivel", 1)
            }
        }
    }

@app.get("/app")
async def servir_frontend():
    return FileResponse("static/index.html")