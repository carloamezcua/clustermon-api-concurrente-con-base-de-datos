# Clustermon API

API REST asíncrona desarrollada con FastAPI y MongoDB Atlas inspirada en la mecánica de una mascota virtual. Permite la gestión de usuarios, reclamo periódico de monedas, obtención aleatoria de criaturas y persistencia no relacional en la nube.

---

## Estructura del Proyecto


---

## Requisitos Previos


---

## Instalación y Puesta en Marcha


---

## Endpoints de la API

### Verificación y Entrenadores
* GET /ping : Comprobación de estado del servidor y conexión
* POST /usuarios : Registro de entrenador con usuario y contraseña
* GET /usuarios/{id} : Consulta del perfil, balance y estado del entrenador
* POST /usuarios/{id}/reclamar : Reclamo periódico de monedas con tiempo de enfriamiento

### Clustermones y Mecánicas de Juego
* POST /clustermones/tirada : Obtención aleatoria de criaturas mediante consumo de monedas
* GET /clustermones/{usuario_id} : Listado de criaturas asociadas a un entrenador
* POST /clustermones/{id}/entrenar : Incremento de estadísticas de una criatura

---

## Modelo de Datos

### Colección: usuarios
* _id: Identificador único (ObjectId)
* username: Nombre de usuario único
* password: Contraseña de acceso
* monedas: Balance actual disponible
* ultimo_reclamo: Marca de tiempo para validación de cooldown

### Colección: clustermones
* _id: Identificador único (ObjectId)
* usuario_id: Referencia al entrenador dueño (ObjectId)
* nombre: Nombre de la especie
* rareza: Clasificación de obtención
* nivel: Nivel de entrenamiento actual
* ataque: Puntos base de ataque
* defensa: Puntos base de defensa