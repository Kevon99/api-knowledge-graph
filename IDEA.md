# API Knowledge Graph: Plataforma Inteligente para el Análisis de Seguridad de APIs

## Visión General

Actualmente existen excelentes herramientas para interceptar, analizar y probar APIs, como Burp Suite, OWASP ZAP, mitmproxy y diversas plataformas de observabilidad. Sin embargo, todas ellas presentan una limitación importante: muestran el tráfico como una secuencia de peticiones y respuestas, obligando al analista a reconstruir mentalmente cómo interactúan los diferentes componentes de una aplicación.

La propuesta consiste en desarrollar una plataforma capaz de transformar el tráfico HTTP capturado en un **grafo de conocimiento** (Knowledge Graph), donde cada petición deje de ser un evento aislado y pase a formar parte de un modelo completo de la aplicación.

El objetivo no es crear otro visor de tráfico HTTP, sino construir una herramienta que permita comprender el comportamiento interno de una API, descubrir relaciones ocultas, identificar flujos de autenticación, rastrear objetos de negocio, analizar la propagación de tokens y asistir al auditor durante una evaluación de seguridad.

---

# Problema

Durante una auditoría de una API REST, el analista puede llegar a generar decenas de miles de peticiones.

Aunque Burp Suite almacena toda esa información, responder preguntas relativamente sencillas requiere una gran cantidad de trabajo manual.

Por ejemplo:

- ¿Qué endpoints utilizan el mismo JWT?
    
- ¿Qué flujo sigue un usuario desde que inicia sesión hasta que realiza un pago?
    
- ¿Qué objetos de negocio aparecen en diferentes módulos?
    
- ¿Qué recursos son accesibles utilizando un mismo token?
    
- ¿Qué endpoints pertenecen al mismo microservicio?
    
- ¿Qué parámetros son reutilizados durante toda la navegación?
    
- ¿Qué rutas exponen información sensible?
    

Actualmente estas respuestas dependen de la experiencia del auditor y del análisis manual del tráfico.

La herramienta propuesta pretende automatizar ese proceso.

---

# Objetivo Principal

Construir una plataforma que reciba como entrada el tráfico HTTP capturado (inicialmente mediante Burp Suite Logger) y genere automáticamente un modelo navegable del funcionamiento de la aplicación.

Ese modelo estará basado en un grafo de conocimiento donde cada elemento observado durante la navegación se convertirá en una entidad relacionada con el resto del sistema.

El resultado será una representación dinámica de la aplicación desde una perspectiva de seguridad.

---

# Filosofía del Proyecto

El proyecto no pretende almacenar peticiones.

Pretende almacenar conocimiento.

Cada request representa evidencia.

Cada evidencia genera relaciones.

Las relaciones construyen un modelo.

Y ese modelo permite razonar sobre la superficie de ataque de la aplicación.

---

# Primera Fuente de Información

La primera integración será Burp Suite.

Durante una auditoría, el analista simplemente navegará por la aplicación mientras Burp captura todas las peticiones mediante Logger.

Al finalizar, exportará el tráfico.

La plataforma importará dicho archivo y comenzará automáticamente el proceso de análisis.

En futuras versiones podrán incorporarse otros orígenes como:

- HAR.
    
- OpenAPI.
    
- Swagger.
    
- Postman.
    
- mitmproxy.
    
- OpenTelemetry.
    
- PCAP.
    
- Fiddler.
    
- Proxies corporativos.
    

El núcleo del sistema será independiente del origen de los datos.

---

# Flujo General

El funcionamiento del sistema estará dividido en varias etapas.

## 1. Importación

El sistema leerá el archivo exportado por Burp.

Extraerá:

- Peticiones.
    
- Respuestas.
    
- Cabeceras.
    
- Cookies.
    
- Códigos HTTP.
    
- Parámetros.
    
- Cuerpos JSON.
    
- Archivos.
    
- Tiempos.
    
- Dominios.
    
- Subdominios.
    

---

## 2. Normalización

Las rutas dinámicas serán convertidas a plantillas.

Ejemplo:

GET /users/15

GET /users/84

GET /users/912

↓

GET /users/{id}

Esto permitirá identificar recursos en lugar de peticiones individuales.

---

## 3. Identificación de Entidades

El sistema detectará automáticamente elementos como:

- JWT.
    
- Refresh Tokens.
    
- Cookies.
    
- API Keys.
    
- OAuth.
    
- OIDC.
    
- Sessions.
    
- Roles.
    
- Scopes.
    
- Usuarios.
    
- Objetos JSON.
    
- Recursos REST.
    
- Dominios.
    
- Subdominios.
    
- Servicios.
    
- Archivos.
    

Cada uno se convertirá en un nodo del grafo.

---

## 4. Correlación

Esta será la pieza central del proyecto.

La plataforma buscará relaciones automáticamente.

Ejemplos:

Un JWT emitido durante el login será relacionado con todos los endpoints donde posteriormente sea utilizado.

Un customerId observado en varias respuestas permitirá reconstruir el recorrido completo de ese objeto dentro de la aplicación.

Un orderId utilizado en distintos módulos permitirá conectar pedidos, pagos, facturas y envíos.

La herramienta dejará de ver texto y comenzará a entender entidades.

---

## 5. Construcción del Grafo

Cada entidad detectada será representada mediante nodos.

Las relaciones se construirán automáticamente.

Ejemplos:

Login → Emite → JWT

JWT → Autoriza → Endpoint

Endpoint → Devuelve → Order

Order → Utilizado por → Payment

Payment → Genera → Invoice

Invoice → Descargada desde → Endpoint

Así se construirá un modelo navegable de toda la aplicación.

---

# Motor de Conocimiento

El verdadero objetivo no es visualizar grafos.

Es construir conocimiento.

Por ello existirán distintos niveles de confianza.

## Evidencia

Información observada directamente.

Ejemplo:

Un JWT aparece en una respuesta y posteriormente es enviado en la cabecera Authorization.

Esto constituye una relación confirmada.

---

## Inferencia

Relaciones obtenidas mediante correlación.

Ejemplo:

El mismo customerId aparece durante múltiples procesos.

La plataforma infiere que todas esas operaciones pertenecen al mismo recurso.

---

## Hipótesis

Conclusiones razonables pero no confirmadas.

Ejemplo:

Existe GET /users/{id}.

Existe POST /users.

Es probable que también existan PUT o DELETE sobre ese recurso.

Estas hipótesis ayudarán al auditor a descubrir nuevas superficies de ataque.

---

# Vistas del Sistema

La plataforma no mostrará un único grafo.

Dispondrá de diferentes perspectivas.

## Flujo de autenticación

Mostrará:

Login

↓

JWT

↓

Refresh Token

↓

Logout

---

## Recursos

Permitirá navegar entre:

Usuarios

Pedidos

Pagos

Facturas

Clientes

Productos

---

## Infraestructura

Representará:

Dominios

Subdominios

Gateways

Microservicios

Bases de datos

Servicios externos

---

## Permisos

Relacionará:

Roles

Scopes

JWT

Endpoints

Recursos protegidos

---

## Timeline

Permitirá reproducir cronológicamente la navegación.

Cada acción podrá abrir inmediatamente la petición original almacenada.

---

# Motor de Reglas

Sobre el conocimiento generado se ejecutarán reglas automáticas.

Ejemplos:

- Reutilización excesiva de JWT.
    
- Reutilización de cookies.
    
- Posibles vulnerabilidades IDOR/BOLA.
    
- Recursos sin autenticación.
    
- Endpoints que ignoran scopes.
    
- Tokens con privilegios elevados.
    
- Objetos sensibles expuestos.
    
- Flujos de autenticación inconsistentes.
    

Las reglas producirán alertas enriquecidas con el contexto del grafo.

---

# Inteligencia Artificial

La IA no será utilizada para interpretar el tráfico original.

Será utilizada sobre el conocimiento ya estructurado.

Permitirá responder preguntas como:

- ¿Cómo llega un usuario autenticado hasta el módulo de pagos?
    
- ¿Qué endpoints utilizan el mismo JWT?
    
- ¿Qué rutas acceden al objeto Customer?
    
- ¿Cuál es el recorrido completo de una factura?
    
- ¿Qué objetos aparecen en varios microservicios?
    
- ¿Qué recursos parecen especialmente críticos?
    

La IA trabajará sobre un subconjunto del grafo para mantener respuestas precisas y eficientes.

---

# Objetivo Final

El propósito del proyecto es convertirse en una herramienta equivalente a lo que BloodHound representa para Active Directory, pero aplicada al análisis de APIs modernas.

No se limitará a visualizar tráfico.

Construirá un modelo navegable de conocimiento.

Permitirá comprender el funcionamiento interno de una aplicación.

Reducirá significativamente el tiempo necesario para entender sistemas complejos.

Facilitará la identificación de riesgos de seguridad.

Y proporcionará al auditor una nueva forma de explorar, consultar y razonar sobre la superficie de ataque de una API.

En esencia, la plataforma transformará miles de peticiones HTTP dispersas en un mapa inteligente y navegable del comportamiento real de una aplicación, convirtiendo el análisis de APIs desde una actividad manual y lineal en un proceso basado en conocimiento, relaciones y evidencia.