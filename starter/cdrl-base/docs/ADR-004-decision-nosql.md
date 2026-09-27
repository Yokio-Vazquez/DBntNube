# ADR-004 - Decision de almacenamiento NoSQL para M04

## Estado

Propuesta seleccionada: Amazon DynamoDB como almacenamiento complementario, pendiente de validar las hipotesis de carga y costo.

## Contexto y alcance

El CDRL ya usa PostgreSQL para el catalogo de juegos, las relaciones con plataformas y la integridad de las metricas. La decision M04 no reemplaza ese contrato relacional. Evalua un almacen complementario para metricas/eventos operativos consultados principalmente por juego y tiempo, con escala variable. La decision se basa en los patrones visibles en M02; el repositorio aun no implementa una integracion de la API con DynamoDB.

## Tipos NoSQL evaluados

- **Documentos - MongoDB.** Los registros se almacenan como documentos BSON con campos anidados y esquema flexible. Embebido o referencia se elige segun los patrones de acceso. Es adecuado cuando los atributos varian o se recuperan juntos; joins y agregaciones entre colecciones requieren otro diseno que las tablas relacionales.
- **Grafos - Neo4j.** Los nodos representan entidades y las relaciones tipadas conectan nodos y pueden tener propiedades. Destaca cuando las consultas recorren caminos o conexiones de profundidad variable; no es el patron principal de lectura/escritura de metricas por clave del CDRL.
- **Wide-column - Apache Cassandra.** Las tablas se particionan por una partition key y pueden ordenar filas con clustering keys. Las consultas eficientes se disenan alrededor de esas claves; no ofrece joins distribuidos ni claves foraneas. La consistencia se configura por operacion/consistency level y exige operar el cluster.
- **Clave-valor/documento - Amazon DynamoDB.** DynamoDB ofrece elementos direccionados por clave primaria, operaciones `GetItem`/`Query`, indices secundarios, capacidad bajo demanda y lecturas fuertemente consistentes opcionales en tabla/LSI. Las lecturas de GSI y Streams son eventualmente consistentes. Nota de taxonomia: algunas guias docentes lo agrupan con Column, pero AWS describe su modelo como clave-valor y documento; no es una tabla wide-column de Cassandra.
- **Objetos - Amazon S3.** Los datos son objetos dentro de buckets, identificados por clave y opcionalmente version. Tiene consistencia fuerte read-after-write para objetos, escala y clases de almacenamiento, pero no ofrece consultas operacionales por campos arbitrarios o transacciones entre claves como una base de datos de registros.

## Criterios y pesos

Escala de calificacion: 1 = ajuste bajo, 3 = suficiente con compromisos, 5 = ajuste alto. Las calificaciones son una evaluacion arquitectonica preliminar, no resultados de un benchmark. `puntaje ponderado = suma(peso * calificacion)` y `normalizado = puntaje ponderado / 5`, en escala de 0 a 100.

| Criterio | Peso | Razon |
| --- | ---: | --- |
| Consultas | 30% | El caso prioritario es leer/escribir metricas por juego y ventana temporal. |
| Escala | 25% | El volumen de eventos puede crecer y tener picos. |
| Consistencia | 20% | Una medicion aceptada debe poder verificarse; se documentan las lecturas eventualmente consistentes. |
| Costo | 15% | El equipo debe poder probar en Learner Lab y estimar costo sin operar infraestructura innecesaria. |
| Fallos | 10% | Se valora disponibilidad administrada, recuperacion y comportamiento ante throttling/errores. |

## Matriz ponderada

| Alternativa | Tipo evaluado | Consultas (30) | Escala (25) | Consistencia (20) | Costo (15) | Fallos (10) | Total / 500 | Normalizado / 100 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| MongoDB | Documentos | 4 | 4 | 4 | 3 | 3 | 375 | 75 |
| Neo4j | Grafo | 2 | 3 | 4 | 2 | 3 | 275 | 55 |
| Apache Cassandra | Wide-column | 3 | 5 | 3 | 2 | 4 | 345 | 69 |
| Amazon DynamoDB | Clave-valor/documento (grupo Column de la guia) | 5 | 5 | 4 | 4 | 5 | 465 | 93 |
| Amazon S3 | Objetos | 2 | 5 | 4 | 5 | 5 | 390 | 78 |

La alternativa seleccionada es DynamoDB por el mayor resultado ponderado (93/100). Los puntajes expresan adecuacion prevista al caso y deben revisarse si cambian las consultas, el volumen o los limites de costo.

## Decision y alternativa descartada

Se propone DynamoDB para eventos/metricas operativas con una clave de particion basada en `game_id` y una clave de ordenamiento basada en tipo de metrica y tiempo. Asi, `Query` puede devolver las mediciones de un juego dentro de un rango temporal sin escanear toda la tabla. PostgreSQL conserva juegos, plataformas, relaciones y restricciones como fuente de verdad.

Se descarta MongoDB como almacen operacional de este flujo: su modelo documental es flexible, pero el contrato actual tiene atributos estables, relaciones normalizadas y consultas dominadas por claves conocidas. Adoptarlo agregaria otro motor y trabajo de operacion/modelado sin demostrar una ventaja sobre `Query` de DynamoDB para el acceso por juego/tiempo. No se afirma que MongoDB sea inferior en general; seria reconsiderado si el CDRL comenzara a almacenar payloads heterogeneos que se lean como documentos completos.

S3 tambien se descarta para consultas en linea de metricas, aunque podria complementar el sistema como archivo barato de exportaciones o datos historicos. Neo4j no se justifica mientras las preguntas no dependan de recorridos de relaciones entre entidades. Cassandra ofrece alta escala de escritura, pero su operacion de cluster y restricciones de consulta no se justifican para el alcance actual frente al servicio administrado.

## Hipotesis falsables y plan de evidencia

Las cinco hipotesis estan pendientes; DynamoDB Local sirve para desarrollo funcional, pero no demuestra latencia AWS, costos administrados, escalado ni alta disponibilidad del servicio.

1. **Consultas:** con 100,000 metricas sinteticas, una clave `game_id` + `metric_name#timestamp` y 1,000 solicitudes/segundo, al menos 95% de las lecturas por juego/rango usaran `Query` (no `Scan`) y tendran p95 menor a 20 ms en una prueba AWS. Se refuta si el patron exige `Scan` o excede el umbral.
2. **Escala:** al subir de 100 a 1,000 solicitudes/segundo durante 15 minutos en modo on-demand, throttling sera menor a 0.1% y p95 permanecera debajo de 20 ms. Se refuta si cualquiera de esos limites se supera; registrar metricas CloudWatch y errores SDK.
3. **Consistencia:** en 1,000 ciclos `PutItem` seguido de lectura con `ConsistentRead=true` desde la tabla base, el siguiente `GetItem`/`Query` observara el valor confirmado en 100% de los ciclos. Repetir con GSI para documentar que sus lecturas son eventualmente consistentes; no se usaran como prueba de lectura fuerte.
4. **Costo:** para un perfil explicito de 1 millon de escrituras, 10 millones de lecturas de 1 KB y 10 GB almacenados al mes en `us-east-1`, el estimador oficial proyectara menos de USD 25/mes, excluyendo free tier, streams y servicios auxiliares. Se refuta si el estimado supera el presupuesto; guardar captura/exportacion de AWS Pricing Calculator.
5. **Fallos:** durante 10 minutos, inyectar 1% de throttling/timeouts/errores 5xx y usar reintentos acotados con backoff exponencial y jitter. La aplicacion recuperara al menos 99.9% de operaciones, sin duplicar eventos con el mismo identificador externo. Se refuta si cae por debajo del umbral o hay duplicados/perdida confirmada.

## Riesgos y consecuencias

- El modelo debe fijarse por patrones de acceso; DynamoDB no ofrece joins y los GSI son eventualmente consistentes.
- Una mala distribucion de claves puede crear particiones calientes; medir distribucion y throttling antes de aceptar.
- El precio depende de tamano de item, region, lecturas/escrituras, indices, backups y modo de capacidad. La puntuacion de costo no sustituye la calculadora.
- NoSQL Local en Docker no representa disponibilidad multi-AZ ni rendimiento AWS; usarlo solo para pruebas funcionales y reservar pruebas de servicio para Learner Lab si esta habilitado.
- Esta ADR es una decision de arquitectura; no declara que la integracion NoSQL ya este implementada.

## Cambios incluidos en esta entrega

- Se documentaron y puntuaron cinco alternativas que cubren los tipos documental, grafo, wide-column, clave-valor/documento y objetos.
- Se selecciono provisionalmente DynamoDB como complemento de PostgreSQL y se registraron cinco hipotesis falsables con sus metodos de validacion.
- Se creo `artifacts/m04-nosql-decision-results.json` con los pesos, puntuaciones, totales ponderados y opcion seleccionada.
- Se extendio `scripts/verify_base.py` para validar que los pesos sumen 100, que la aritmetica de la matriz sea consistente y que la opcion seleccionada tenga la puntuacion mayor.
- Se permitio versionar el artefacto M04 mediante una excepcion especifica en `.gitignore`.

La comprobacion automatizada confirmo el JSON, los pesos y los totales; las hipotesis de rendimiento, consistencia, costo y recuperacion permanecen pendientes de ejecucion.

## Fuentes

- MongoDB, *Data Modeling*: https://www.mongodb.com/docs/manual/data-modeling/
- Neo4j, *What is a graph database*: https://neo4j.com/docs/getting-started/graph-database/
- Apache Cassandra, *Architecture overview*: https://cassandra.apache.org/doc/latest/cassandra/architecture/overview.html
- AWS, *What is Amazon DynamoDB?*: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/Introduction.html
- AWS, *DynamoDB read consistency*: https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/HowItWorks.ReadConsistency.html
- AWS, *What is Amazon S3?*: https://docs.aws.amazon.com/AmazonS3/latest/userguide/Welcome.html
- AWS, *Amazon DynamoDB pricing*: https://aws.amazon.com/dynamodb/pricing/