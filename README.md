# Clustermones - Backend API & Web Dashboard

## 1. Descripción del Proyecto

Clustermones es una API REST asíncrona para un juego de colección tipo Gacha/Idle. El sistema administra entrenadores, monedas, invocaciones aleatorias, progresión de criaturas, liberaciones e intercambios, manteniendo la información persistida en MongoDB Atlas.

La solución utiliza una arquitectura desacoplada: FastAPI expone la lógica de negocio y los recursos HTTP, mientras que un cliente web construido con HTML, CSS y JavaScript consume la API mediante `fetch`. El backend también sirve el dashboard desde `/app`, por lo que ambos componentes pueden ejecutarse desde el mismo servidor durante el desarrollo.

## 2. Pila Tecnológica

| Capa | Tecnologías | Uso en el proyecto |
| --- | --- | --- |
| Backend | FastAPI, Uvicorn | Definición de rutas REST y servidor ASGI de desarrollo |
| Acceso a datos | Motor, `AsyncIOMotorClient` | Conexiones y operaciones asíncronas con MongoDB |
| Validación | Pydantic | Validación del registro de usuarios mediante modelos y restricciones de longitud |
| Base de datos | MongoDB Atlas | Persistencia documental en la nube |
| Modelo de relación | Referencias manuales con `ObjectId` | Asociación entre usuarios y Clustermones mediante `usuario_id` |
| Frontend | HTML5, CSS3 y JavaScript | Dashboard web y presentación de la información |
| Comunicación | Fetch API asíncrono | Consumo de endpoints sin recargar la página |
| Configuración | `python-dotenv` | Carga de variables desde `.env` |

## 3. Modelo de Datos y Persistencia (MongoDB Atlas)

La aplicación abre un cliente `AsyncIOMotorClient` durante el ciclo de vida de FastAPI y asigna las colecciones a `app.state.usuarios` y `app.state.clustermones`. Los nombres pueden configurarse mediante variables de entorno.

### Colección `usuarios`

Cada documento contiene, como mínimo:

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `_id` | `ObjectId` | Identificador generado por MongoDB |
| `usuario` | `string` | Nombre persistido del entrenador |
| `contraseña` | `string` | Valor recibido al registrar la cuenta |
| `monedas` | `number` | Saldo actual del entrenador |
| `ultimo_reclamo` | `datetime` o `null` | Marca de tiempo del último reclamo |

El endpoint `POST /usuarios` recibe los campos `usuario` y `password`, y los persiste como `usuario` y `contraseña`. El campo de contraseña no se utiliza para autenticación en esta entrega y debe protegerse o aplicar hash antes de usar el sistema en producción.

### Colección `clustermones`

Cada documento representa una criatura y contiene:

| Campo | Tipo | Descripción |
| --- | --- | --- |
| `_id` | `ObjectId` | Identificador único de la criatura |
| `usuario_id` | `ObjectId` | Referencia manual al dueño en `usuarios` |
| `nombre` | `string` | Especie obtenida del catálogo |
| `rareza` | `string` | Categoría de rareza de la criatura |
| `nivel` | `number` | Nivel actual; inicia en `1` |

### Decisión de persistencia

Se utilizan referencias manuales porque un entrenador puede tener múltiples Clustermones y cada criatura cambia de dueño durante un intercambio. Guardar `usuario_id` como `ObjectId` evita duplicar los datos del entrenador en cada criatura, facilita listar el inventario con una consulta por propietario y permite cambiar la propiedad actualizando únicamente la referencia.

## 4. Reglas de Negocio y Mecánicas del Juego

### Gacha / Invocación

- Cada tirada cuesta `100` monedas (`COSTO_TIRADA`).
- El saldo se valida antes de descontar el costo.
- La rareza se selecciona mediante `random.choices` con probabilidades ponderadas y después se elige una especie al azar dentro de la categoría.
- La criatura se guarda con nivel inicial `1`.
- Las categorías y probabilidades configuradas son:

	| Rareza | Probabilidad |
	| --- | ---: |
	| Común | 55.0% |
	| Poco Común | 25.0% |
	| Raro | 14.0% |
	| Épico | 5.9% |
	| Legendario | 0.1% (1/1000) |

### Economía y Recompensa Diaria

Cada usuario comienza con `100` monedas. El endpoint de reclamo otorga `50` monedas y establece `ultimo_reclamo` usando `datetime.now(timezone.utc)`. El siguiente reclamo se bloquea durante `60` segundos. La validación normaliza fechas sin zona horaria a UTC y devuelve el tiempo restante en segundos (`Xs`) o minutos y segundos (`Xm Ys`).

### Progresión (Subir Nivel)

No existe un nivel máximo. El costo para pasar desde el nivel actual al siguiente se calcula como:

$$
	ext{costo} = \operatorname{round}(20 \times 1.07^{(\text{nivel actual} - 1)})
$$

La constante base es `20` y el factor exponencial es `1.07`. El incremento moderado permite una inversión continua sin que el costo crezca de forma desmedida. El saldo se descuenta y el nivel se incrementa en la base de datos únicamente después de superar las validaciones de usuario, existencia, pertenencia y saldo.

### Liberación

Liberar elimina físicamente el documento del Clustermon. Antes de hacerlo, la API valida el formato de ambos `ObjectId`, la existencia del usuario y la existencia de la criatura, además de comprobar que `usuario_id` coincide con el usuario solicitante. La operación devuelve `20` monedas al entrenador.

### Centro de Intercambio (Trade mutuo)

El intercambio recibe dos usuarios y una criatura de cada uno. Valida que los cuatro identificadores sean válidos, que los usuarios sean distintos, que las criaturas existan y que cada criatura pertenezca al entrenador indicado. Después cruza los dos valores `usuario_id` mediante dos actualizaciones de MongoDB.

La implementación realiza el cruce lógico de manera consecutiva; no utiliza una sesión ni una transacción MongoDB formal. Por ello, la atomicidad transaccional completa requeriría añadir una transacción explícita para garantizar que ambas actualizaciones se confirmen o se deshagan juntas.

## 5. Catálogo de Endpoints de la API

Los identificadores de usuario y Clustermon se esperan como cadenas con formato `ObjectId` de MongoDB.

| Método HTTP | Ruta | Descripción | Códigos esperados |
| --- | --- | --- | --- |
| `GET` | `/ping` | Comprueba que el servidor responde. | `200` |
| `POST` | `/usuarios` | Registra un entrenador con `usuario` y `password`; asigna 100 monedas iniciales. | `201`, `400` |
| `GET` | `/usuarios/{id}` | Consulta el perfil y el saldo, sin devolver la contraseña. | `200`, `400`, `404` |
| `POST` | `/usuarios/{usuario_id}/reclamar` | Reclama 50 monedas respetando el cooldown de 60 segundos. | `200`, `400`, `404` |
| `GET` | `/clustermones/clusterdex` | Devuelve el catálogo, el total de especies, las probabilidades y el costo de tirada. | `200` |
| `GET` | `/clustermones/{usuario_id}` | Lista el inventario del entrenador. | `200`, `400`, `404` |
| `POST` | `/clustermones/tirada/{usuario_id}` | Ejecuta una invocación, descuenta 100 monedas y persiste la criatura. | `200`, `400`, `404` |
| `DELETE` | `/clustermones/{id}/usuario/{usuario_id}` | Libera una criatura del usuario y reembolsa 20 monedas. | `200`, `400`, `403`, `404` |
| `POST` | `/clustermones/{id}/subir-nivel/{usuario_id}` | Incrementa el nivel y cobra el costo exponencial correspondiente. | `200`, `400`, `403`, `404` |
| `POST` | `/clustermones/intercambiar/{usuario1_id}/{clustermon1_id}/{usuario2_id}/{clustermon2_id}` | Intercambia la propiedad de dos criaturas entre dos entrenadores. | `200`, `400`, `403`, `404` |
| `GET` | `/app` | Sirve el dashboard web desde `static/index.html`. | `200` |

Los errores de validación de identificadores, saldo insuficiente, cooldown, duplicidad o reglas de negocio se devuelven normalmente como `400`. La falta de recursos produce `404` y un intento de operar sobre una criatura que no pertenece al usuario produce `403`.

## 6. Cliente Web Frontend (/app)

La ruta `GET /app` utiliza `FileResponse` para servir `static/index.html`. El dashboard es una SPA básica sin framework: actualiza el DOM y consume la API con `fetch` asíncrono, mostrando los resultados sin recargar la página.

La interfaz incluye los siguientes módulos:

- **Consulta del entrenador:** recibe un `ObjectId`, consulta el perfil y muestra el saldo actualizado en tiempo real.
- **Recompensa:** permite reclamar las monedas y presenta errores de cooldown o conexión.
- **Inventario:** lista nombre, rareza, nivel e identificador de cada Clustermon asociado al usuario.
- **Invocador Gacha:** ejecuta una tirada, muestra la criatura obtenida y refresca saldo e inventario.
- **Progresión:** permite subir una criatura de nivel y muestra el costo descontado.
- **Liberación:** solicita confirmación, elimina la criatura y actualiza el saldo y el inventario.
- **Centro de Intercambio:** recibe los dos usuarios y las dos criaturas, ejecuta el trade y refresca el inventario del usuario activo.

## 7. Instalación y Puesta en Marcha

### Prerrequisitos

- Python `3.10` o superior.
- Un clúster operativo de MongoDB Atlas.
- Una cadena de conexión con permisos de lectura y escritura sobre la base de datos.

### Crear el entorno e instalar dependencias

Desde la carpeta del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install fastapi uvicorn motor pydantic python-dotenv
```

También puede instalarse la dependencia declarada en `requirements.txt`:

```powershell
pip install -r requirements.txt
```

### Configurar `.env`

Copie `.env.example` como `.env` y sustituya los valores de conexión por los de su clúster. La estructura requerida es:

```env
MONGODB_URI="mongodb+srv://<usuario>:<password>@<tu-cluster>.mongodb.net/"
DATABASE_NAME="ClustermonDB"
COLL_USUARIOS="usuarios"
COLL_CLUSTERMONES="clustermones"
```

El archivo `.env` está excluido mediante `.gitignore`; no debe publicarse porque contiene credenciales de MongoDB Atlas.

### Arrancar el servidor

```powershell
uvicorn main:app --reload
```

Con el servidor activo, las URLs locales principales son:

- Dashboard del juego: `http://127.0.0.1:8000/app`
- Documentación interactiva Swagger UI: `http://127.0.0.1:8000/docs`
- Comprobación de disponibilidad: `http://127.0.0.1:8000/ping`