# Plan: suscripciones, límites de uso y panel de administración

**Fecha:** 21-oct-2026 · **Estado:** propuesta para aprobar; no hay nada integrado.
Los costos salen de **mediciones reales** (tokens de cada operación con el modelo de producción) y
de precios verificados el 21-oct-2026. Lo que no se pudo verificar en fuente oficial va marcado.

## 1. Valoración

**Conviene, con condiciones.** Laria ya cuesta poco por alumno: el modelo barato (gpt-4o-mini)
hace casi todo el trabajo, y la economía de tokens está medida. Pero hay cuatro cosas que decidir
antes de cobrar:

1. **La voz es el costo grande.** Un minuto de voz cuesta lo mismo que unos **30 mensajes** o
   **60 minutos de clase sin voz**. Los planes tienen que limitarla en minutos; el resto apenas pesa.
2. **No hay datos de uso real todavía.** El piloto tiene 51 usuarios, con una mediana de **2
   mensajes por usuario** (como mucho 76) y **5,5 minutos de estudio al día** (como mucho 20). Los
   precios de abajo son un punto de partida razonado; hay que **medir el costo real por usuario
   antes de fijarlos** (fase M0).
3. **Hoy la infraestructura no sirve para cobrar:**
   - **Vercel Hobby no admite uso comercial:** hace falta Pro, 20 USD al mes.
   - **Render gratis duerme el servidor:** un cliente que paga no puede esperar 4 minutos.
     Starter cuesta 7 USD al mes.
   - **Clerk sigue en la instancia de desarrollo** (`pk_test`).
   - **Términos y privacidad tienen 10 huecos `[[COMPLETAR]]`.** No se puede cobrar con textos
     legales incompletos, y hay que añadir pagos, cancelación y reembolsos.
4. **Hay menores entre los usuarios.** El pago lo tiene que hacer un adulto. La privacidad ya los
   contempla, pero el flujo de pago debe pedir un responsable.

## 2. Costos unitarios (medidos)

Precios oficiales de OpenAI (21-oct-2026), por millón de tokens:
- **gpt-4o-mini:** 0,15 USD de entrada y 0,60 de salida.
- **gpt-4o:** 2,50 y 10,00 USD.
- **gpt-4o-mini-tts:** unos **0,015 USD por minuto de audio**, según la estimación de OpenAI.
- **Búsqueda web:** 10 USD por cada mil búsquedas.
- **Moderación:** gratis.

| Operación | Tokens medidos (entrada / salida) | Costo |
|---|---|---|
| Mensaje del chat (con historial) | 524 / 197 | 0,0002 USD |
| Duda en clase (con el contexto del paso) | 862 / 115 | 0,0002 USD |
| Paso de clase: lección con comprobación 3+3 | 741 / 898 | 0,00065 USD |
| Corregir una respuesta abierta | 277 / 91 | 0,0001 USD |
| **Paso de clase completo** (lección + 3 correcciones) | — | **0,00094 USD** |
| Nivelación básica (4 abiertas + corrección) | 618 / 654 | 0,0009 USD |
| Nivelación avanzada (gpt-4o) | — | ~0,015 USD |
| Temario investigado en internet (gpt-4o + búsqueda) | ~18 000 en total | ~0,08 USD **una vez por tema y nivel, para todos** |
| **Minuto de voz** | — | **~0,015 USD** |

**Para planificar** (con margen: un mensaje con documento y memoria cuesta unas 2,5 veces lo medido):
- **Mensaje:** 0,0005 USD.
- **Minuto de clase:** 0,00024 USD, con un paso cada 4 minutos.
- **Minuto de voz:** 0,015 USD.

**Costos fijos al cobrar**, por mes:

| Servicio | Costo |
|---|---|
| Render Starter | 7 USD; Standard cuesta 25 USD, para cuando haya carga |
| Vercel Pro | 20 USD |
| Clerk | Gratis hasta 50 000 usuarios retenidos al mes; Pro cuesta 25 USD (fuente de Clerk, sin confirmar en su página de precios) |
| Atlas | M0 gratis hasta 512 MB (hoy se usan 2,4); después hay que pasar a un plan de pago, **precio por verificar** |
| Upstash y R2 | Planes gratis por ahora |

**Total:** unos **30–60 USD al mes**. Con el plan Estudiante, se cubre con **5 a 10 suscripciones**.

**Comisiones de pago:**
- **Stripe en México:** unos 3,6 % + 3 MXN por cobro, más IVA. Lo dicen fuentes de terceros; hay que
  confirmarlo en stripe.com/mx/pricing.
- **Clerk Billing** añade un 0,7 % por encima de Stripe.

## 3. Los cuatro planes

Los límites son **mensuales**, con un tope diario contra abusos. Una **duda en clase** cuenta como
mensaje. La **clase** se mide en minutos con el tiempo de estudio que ya cuenta el servidor
(ADR-033).

| | **Gratis** | **Estudiante** | **Pro** | **Institución** (por alumno) |
|---|---|---|---|---|
| Precio | 0 | **6,99 USD/mes** | **12,99 USD/mes** | **3,99 USD/mes**, mínimo 20 alumnos, pago anual |
| Mensajes con la IA | 300/mes (30/día) | 2 000/mes (150/día) | 5 000/mes (300/día) | 1 500/mes |
| Tiempo de clase | 5 h/mes (30 min/día) | 30 h/mes (3 h/día) | 60 h/mes | 25 h/mes |
| Voz del tutor | 10 min/mes | 90 min/mes | 180 min/mes | 45 min/mes |
| Documentos | 3 | 20/mes | 60/mes | 15/mes |
| Preguntas abiertas, repasos, métodos | Sí | Sí | Sí | Sí |
| Modelo fuerte en el nivel avanzado | No | No | Sí | No |
| Panel docente (progreso del grupo) | — | — | — | Sí |
| **Costo de API si se agota todo** | 0,43 USD | 2,91 USD (42 %) | 6,40 USD (49 %) | 1,90 USD (48 %) |
| **Costo típico** (~15 % del tope) | ~0,07 USD | ~0,44 USD | ~1,0 USD | ~0,30 USD |

**Por qué así:**
- **Todos los planes incluyen preguntas abiertas, repasos y métodos de estudio.** Son lo que
  distingue a Laria. Lo que se limita es la cantidad, no la pedagogía: limitar la calidad del
  aprendizaje a quien no paga sería ir contra el producto.
- **El peor caso queda por debajo del 50 % del precio** incluso si alguien agota todo, y el caso
  típico deja más del 85 % de margen.
- **La voz es lo que más sube entre planes:** es el costo real y lo que más se nota.
- **Gratis** sirve para captar alumnos: su costo máximo son 0,43 USD al mes por usuario.
- **Institución** escala con escuelas o academias, y necesita el panel docente (fase M4).

**Ajustes para abaratar después, sin cambiar los planes:**
- **Probar `gpt-6-luna`:** cuesta 0,10/0,50 USD frente a 0,15/0,60 de gpt-4o-mini, unos 25 % menos.
  Antes hay que repetir los bancos de calidad (ADR-052).
- **Voz del navegador en el plan Gratis:** no cuesta nada, aunque suena peor.
- **Caché de prompts de OpenAI:** la entrada en caché cuesta la mitad.

## 4. Panel de administración y cuentas exentas

**Quién administra:**
- **Superadministrador:** tu cuenta, la del correo `ADMIN_EMAIL` del entorno. No se puede quitar
  desde el panel.
- **Administradores:** los que tú designes en el panel. Pueden gestionar planes y exenciones, pero
  no crear otros administradores.

**Qué guarda el sistema por cada usuario:**
- **Plan:** `free`, `student`, `pro` o `institution`.
- **Exención de cobro:**
  - `billing_exempt`;
  - `exempt_reason`: obligatoria, por ejemplo «fundador», «docente piloto» o «beca»;
  - `exempt_until`: opcional; vacía, la exención es indefinida;
  - `exempt_plan`: el plan que disfruta sin pagar; por defecto, Pro.
- **Uso del mes:** mensajes, minutos de clase, minutos de voz, documentos y **costo real en USD**.
  El costo sale de los tokens que devuelve cada llamada al modelo, no de una estimación.
- **Auditoría:** quién cambió qué y cuándo. **Toda exención queda registrada.**

**Qué hace el panel:**
1. **Usuarios:** buscar por correo o nombre y ver plan, exención, uso y costo del mes.
2. **Exentar o quitar la exención,** con motivo y fecha de fin opcional. Tu cuenta y la de quien
   designes, sin cobro.
3. **Cambiar el plan de forma manual,** para soporte o para las instituciones.
4. **Métricas:**
   - usuarios por plan e ingresos mensuales recurrentes;
   - costo de API por plan;
   - margen real;
   - quién se acerca a sus límites;
   - las cuentas exentas y cuánto cuestan.
5. **Registro de auditoría.**

**Qué ve el alumno:**
- Su plan, cuánto le queda en el mes y cuándo se renueva.
- **Al llegar a un límite**, recibe un aviso claro y la opción de mejorar el plan. Técnicamente es
  un error `402 {reason: "plan_limit_reached", limit, resets_at}`, con el formato `reason` de
  siempre. Una clase a medias **no se corta**: el límite se aplica al pedir el paso siguiente.

## 5. Cobro: proveedor recomendado

| Opción | A favor | En contra |
|---|---|---|
| **Clerk Billing** (sobre Stripe) | Va con la autenticación que ya hay; planes y funciones en el panel de Clerk; poco código | +0,7 %; sin precios por cliente ni cobro por uso; hay que **confirmar que funciona en México y en MXN** |
| **Stripe directo** (Checkout + portal del cliente + webhooks) | Control total; precios para instituciones; cobro anual | Más código (webhooks, conciliación) |
| **Mercado Pago** (suscripciones) | El más usado en LATAM; métodos locales | Integración aparte; APIs menos cómodas |

**Recomendación:** **Stripe directo** para Estudiante y Pro, y **factura manual** para Institución
al principio (el plan se activa desde el panel). Si cobras en México: la **factura CFDI** exige un
proveedor como Facturapi. Lo decides según el país y el régimen fiscal.

## 6. Fases

| Fase | Qué | Quién |
|---|---|---|
| **M0 · Medir** | Registro de uso y costo real por usuario y operación. Sin límites ni cobro. 2–4 semanas de datos para fijar precios con evidencia | Backend |
| **M1 · Planes, límites y panel** | Planes y sus límites en el backend, con un interruptor para que primero solo se registre qué se habría bloqueado. Panel de administración con exenciones y auditoría. **Tu cuenta exenta desde el primer día** | Backend y frontend |
| **M2 · Cobro** | Proveedor de pago, alta y baja, webhooks y portal del cliente. Requisitos previos: Vercel Pro, Render Starter, Clerk de producción y textos legales completos | Los dos, y tú con las cuentas |
| **M3 · Precios definitivos** | Ajustar límites y precios con los datos de M0 y M1 | Tú, con mi análisis |
| **M4 · Institución** | Grupos, panel docente y facturación anual | Los dos |

## 7. Lo que tienes que decidir

1. **País y moneda del cobro** (USD o MXN): define el proveedor, las comisiones y la factura.
2. **Los precios y límites de la tabla,** o pedir ajustes. Son provisionales hasta tener los datos de
   M0.
3. **El proveedor de pago:** Stripe directo (recomendado), Clerk Billing o Mercado Pago.
4. **Si se empieza por M0 y M1 sin cobrar,** que es mi recomendación: así se miden los costos reales
   y tu cuenta queda exenta desde ya.

## Fuentes

- Precios de OpenAI: https://platform.openai.com/docs/pricing (consultado el 21-oct-2026).
- Voz: estimación de 0,015 USD por minuto publicada por OpenAI y comentada en su foro.
- Vercel: https://makerkit.dev/blog/saas/vercel-cost, https://schematichq.com/blog/vercel-pricing
  (confirmar en vercel.com/pricing).
- Render: https://render.com/pricing.
- Clerk: https://clerk.com/articles/clerk-pricing-explained, https://dodopayments.com/blogs/clerk-billing.
- Stripe en México: https://globalfeecalculator.com/blog/stripe-fees-by-country/ (confirmar en
  stripe.com/mx/pricing).
