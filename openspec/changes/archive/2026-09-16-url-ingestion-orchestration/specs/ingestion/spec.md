## Purpose

Esta capacidad define el punto de entrada de la ingesta del MVP: recibir la URL del sitio del prospecto, validar el destino de red, arrancar el pipeline en segundo plano y mantener un estado del onboarding consultable con sus vías de ingesta (primaria URL; secundarias PDF/brochure).

## ADDED Requirements

### Requirement: Entrada de URL y validación del destino de ingesta

El sistema SHALL exponer `POST /api/v1/onboardings` para recibir la URL del sitio de un prospecto y SHALL validar el destino antes de aceptarlo: esquema `http`/`https` únicamente; sin credenciales embebidas; sin nombres de host locales; sin direcciones IP de rangos privados, loopback, link-local, no especificadas, multicast ni de metadatos de nube (p. ej. `169.254.169.254`); y con resolución DNS cuyas direcciones resultantes SHALL verificarse contra los mismos rangos. Si la URL es rechazada, el sistema SHALL responder `422` con un código de motivo estable y SHALL NOT devolver el texto crudo de la excepción. En esta capacidad no se realiza petición saliente a la URL.

Trazabilidad: ORB-FR-002, ORB-FR-005, ORB-INT-004.

#### Scenario: URL pública válida aceptada
- **WHEN** el cliente envía `POST /api/v1/onboardings` con una URL `https` cuyo host resuelve a direcciones públicas
- **THEN** el sistema responde `202` con el identificador de onboarding y el estado inicial

#### Scenario: Esquema no permitido
- **WHEN** la URL usa un esquema distinto de `http`/`https` (p. ej. `ftp://`, `file://`)
- **THEN** el sistema responde `422` con el motivo de esquema no permitido

#### Scenario: Credenciales embebidas en la URL
- **WHEN** la URL contiene usuario o contraseña embebidos (`https://usuario:clave@host/...`)
- **THEN** el sistema responde `422` con el motivo de credenciales no permitidas

#### Scenario: Nombre de host local
- **WHEN** la URL apunta a `localhost`, `*.localhost`, `*.local`, `*.internal` o `*.home.arpa`
- **THEN** el sistema responde `422` con el motivo de host no permitido

#### Scenario: IP literal en rango bloqueado
- **WHEN** la URL usa una IP literal en rangos privados, loopback, link-local o de metadatos de nube
- **THEN** el sistema responde `422` con el motivo de dirección no permitida

#### Scenario: Host que resuelve a una dirección bloqueada
- **WHEN** el nombre de host resuelve por DNS, total o parcialmente, a direcciones de los rangos bloqueados
- **THEN** el sistema responde `422` con el motivo de dirección no permitida

#### Scenario: DNS no resoluble
- **WHEN** el nombre de host no se puede resolver o la resolución excede el tiempo límite
- **THEN** el sistema responde `422` con el motivo de resolución fallida, sin exponer el texto crudo de la excepción

### Requirement: Arranque no bloqueante del pipeline de ingesta

El sistema SHALL iniciar el pipeline de ingesta en segundo plano, sin esperar a que el trabajo finalice para emitir la respuesta al cliente, y SHALL registrar el arranque en el estado del onboarding y en el log estructurado. La paralelización multihilo y el scraping detallado no forman parte de esta capacidad.

Trazabilidad: ORB-FR-023 (cobertura parcial: el arranque en segundo plano y el no bloqueo son de esta capacidad; la paralelización multihilo y la notificación al usuario pertenecen a ORB-TK-02 y ORB-TK-03), ORB-NFR-017.

#### Scenario: Respuesta sin esperar al trabajo
- **WHEN** la solicitud es aceptada y el trabajo de segundo plano permanece en ejecución
- **THEN** el sistema ya emitió la respuesta `202` (el cliente no espera a la finalización del trabajo)

#### Scenario: Registro del arranque
- **WHEN** el trabajo de segundo plano arranca
- **THEN** el estado del onboarding pasa a `ingestion_started` y se emite un registro estructurado con el identificador de onboarding

#### Scenario: Fallo del trabajo de segundo plano
- **WHEN** el trabajo de segundo plano falla
- **THEN** el estado del onboarding queda en `failed`, se registra el fallo y la respuesta ya emitida no se altera

### Requirement: Estado del onboarding consultable con vías de ingesta

El sistema SHALL registrar y exponer el estado del onboarding con: identificador, URL fuente, vía primaria de ingesta (`url_scraping`), vías secundarias (`pdf`, `brochure`), estado del proceso y marcas de tiempo. La consulta SHALL realizarse con `GET /api/v1/onboardings/{id}` y SHALL responder `404` si el identificador no existe.

Trazabilidad: ORB-FR-004, ORB-FR-005, ORB-INT-004, ORB-FR-019.

#### Scenario: Estado inicial tras la aceptación
- **WHEN** se acepta una URL válida y se consulta el onboarding
- **THEN** el estado registra la vía primaria `url_scraping` y las vías secundarias `pdf` y `brochure`

#### Scenario: Estado tras el arranque
- **WHEN** el trabajo de segundo plano ya arrancó y se consulta el onboarding
- **THEN** el estado refleja `ingestion_started` con la marca de tiempo correspondiente

#### Scenario: Onboarding inexistente
- **WHEN** se consulta un identificador de onboarding que no existe
- **THEN** el sistema responde `404`

### Requirement: Puertos y adaptadores desacoplados para la orquestación

El dominio y los casos de uso SHALL poder ejecutarse sin framework HTTP, sin red y sin infraestructura concreta; los adaptadores (estado del onboarding, programación en segundo plano, resolución DNS y ejecución del pipeline) SHALL consumirse a través de puertos sustituibles en pruebas y en implementaciones futuras.

Trazabilidad: ORB-CON-015, ORB-NFR-008, ORB-CON-003, ORB-NFR-013.

#### Scenario: Caso de uso con adaptadores de prueba
- **WHEN** se ejecuta el caso de uso de arranque con un programador de prueba (que no ejecuta el trabajo) y un resolvedor DNS falso
- **THEN** el caso de uso completa sin FastAPI, sin red y sin almacén persistente

#### Scenario: Almacén de estado sustituible
- **WHEN** se reemplaza el adaptador de estado por otra implementación del mismo puerto
- **THEN** el dominio y el caso de uso no requieren cambios

### Requirement: Configuración por entorno y logging estructurado del arranque

El sistema SHALL leer su configuración desde variables de entorno con valores por defecto documentados en `Backend/.env.example` (sin secretos) y SHALL emitir logs estructurados en el arranque de la ingesta y en la validación, con identificador de solicitud e identificador de onboarding. El sistema SHALL NOT registrar secretos ni credenciales.

Trazabilidad: ORB-NFR-015, ORB-FR-019, ORB-NFR-005.

#### Scenario: Arranque con valores por defecto
- **WHEN** la aplicación arranca sin variables de entorno definidas
- **THEN** usa los valores por defecto documentados en `.env.example`

#### Scenario: Identificadores en el log
- **WHEN** se procesa una solicitud de ingesta
- **THEN** los registros del arranque incluyen el identificador de solicitud y el de onboarding

#### Scenario: Rechazo auditable con motivo seguro
- **WHEN** una URL es rechazada por la validación
- **THEN** el registro incluye el código de motivo y la respuesta al cliente no contiene el texto crudo de la excepción

### Requirement: Límites declarados y decisiones abiertas del MVP

El sistema SHALL operar con estos límites explícitos del MVP: (a) el almacén de estado es en memoria y pierde la información al reiniciar; el adaptador definitivo depende de ORB-INT-006, pendiente de ratificación con datapeers; (b) el endpoint es público y sin autenticación; el límite de tasa queda diferido a un cambio separado, asumiendo el riesgo de abuso y repitiendo la validación de destino en cada admisión; (c) no hay deduplicación por URL: cada solicitud crea un onboarding nuevo, y la idempotencia por clave de cliente queda como decisión abierta. El límite (a) se retira cuando ORB-INT-006 se ratifique con datapeers.

Trazabilidad: ORB-INT-006, ORB-NFR-005, ORB-NFR-010.

#### Scenario: Volatilidad del estado asumida
- **WHEN** el proceso se reinicia
- **THEN** los onboardings creados antes del reinicio dejan de ser consultables (`404`) y este comportamiento es el aceptado mientras ORB-INT-006 no se ratifique

#### Scenario: Endpoint público sin autenticación
- **WHEN** llega una solicitud sin credenciales
- **THEN** el sistema la procesa (no hay autenticación en el MVP) y el riesgo de abuso queda declarado con el límite de tasa diferido

#### Scenario: Dos solicitudes con la misma URL
- **WHEN** llegan dos solicitudes con la misma URL
- **THEN** el sistema crea dos onboardings distintos, cada uno con su propio identificador
