# Aircall – HubSpot y envío WhatsApp

Automatización que **exporta contactos desde HubSpot** y **envía mensajes de bienvenida por WhatsApp** mediante Aircall, asignando cada conversación a un agente.

---

## Estructura del proyecto

```
.
├── README.md
├── .env.example
├── .gitignore
├── requirements.txt
└── hubspot_bienvenida.py   # Script principal (obtener registros + envío bienvenida)
```

- **`hubspot_bienvenida.py`**:  
  - **Obtener registros**: exporta contactos de HubSpot CRM (GraphQL) a un CSV.  
  - **Envío bienvenida**: lee el CSV, envía la plantilla de WhatsApp por Aircall y asigna la conversación al agente indicado.

---

## Requisitos

- **Python 3.9+**
- Dependencias: `requests`, `pandas`, `python-dotenv` (y las indicadas en `requirements.txt`)

Instalación:

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

---

## Configuración (`.env`)

Copia el ejemplo y rellena los valores:

```bash
cp .env.example .env
```

### HubSpot (obtener registros)

| Variable | Descripción |
|----------|-------------|
| `HUBSPOT_EMAIL` | Email (opcional; si está vacío, el login puede hacerse a mano) |
| `HUBSPOT_PASSWORD` | Contraseña (opcional) |
| `HUBSPOT_COOKIE` | Cookies de sesión (Application → Cookies en el navegador) |
| `HUBSPOT_PORTAL_ID` | ID del portal HubSpot |
| `HUBSPOT_ORIGIN` | Origen, p. ej. `https://app-eu1.hubspot.com` |
| `HUBSPOT_STATIC_APP_VERSION` | Versión de la app (ver en peticiones de la UI) |

### Aircall (envío bienvenida)

| Variable | Descripción |
|----------|-------------|
| `AIRCALL_AUTH_TOKEN` | Token Bearer (obtener desde la app Aircall / DevTools). **Obligatorio** para envío. |
| `AIRCALL_ORIGIN` | Origen, p. ej. `https://app.aircall.io` |
| `AIRCALL_CHANNEL` | Canal, p. ej. `WHATSAPP` |
| `AIRCALL_LINE_ID` | ID de la línea |
| `AIRCALL_TEMPLATE_ID` | ID de la plantilla de mensaje |
| `AIRCALL_AGENT_NAME` | Nombre del agente: `Silvia`, `Mar`, `Andrea`, `Miguel` (el `AGENT_ID` se resuelve automáticamente) |
| `AIRCALL_AGENT_ID` | (Opcional) Solo si usas un agente que no esté en la lista anterior |

### Rutas

| Variable | Descripción |
|----------|-------------|
| `CSV_PATH` | Ruta del CSV de entrada/salida, p. ej. `data/data.csv` |

---

## Uso

### Ejecutar el script

```bash
python hubspot_bienvenida.py
```

El script pide por consola:

1. **Nombre de agente** (o usa el de `AIRCALL_AGENT_NAME` si se deja vacío).  
2. **Cantidad** de mensajes a enviar (vacío = todos los del CSV).

Luego ejecuta **envío de bienvenida**: lee `CSV_PATH`, envía la plantilla de WhatsApp y asigna cada conversación al agente indicado.

### Flujo de datos

1. **CSV de entrada**: el archivo en `CSV_PATH` debe tener al menos las columnas `phone`, `firstname`, y opcionalmente `nif`, `nif_expiricy`, `nie_soporte`, `aeat_505`, `iban_digits` para construir el mensaje (casilla 505 / NIF / NIE).
2. **Aircall**: se usa la mutación GraphQL `sendMessageV2` con la plantilla configurada y, a continuación, se asigna la conversación al agente con `assignAircallWorkspaceConversation`.

### Obtener registros desde HubSpot (código existente)

La función `run_obtener_registros(CSV_PATH, ...)` está en el script pero no se llama desde `main()` por defecto. Para exportar contactos de HubSpot a CSV puedes invocarla desde otro script o descomentar la lógica en `main()` según tu flujo (exportar primero y luego ejecutar envío).

---

## Seguridad

- No subas ni compartas `.env`, cookies (`HUBSPOT_COOKIE`) ni tokens (`AIRCALL_AUTH_TOKEN`).
- Rota credenciales y limita permisos.
- Respeta los términos de uso de HubSpot y Aircall.

---

## Troubleshooting

- **HubSpot 401/403**: Revisa que las cookies (incluyendo `hubspotapi-csrf` o `csrf.app`) sean del dominio correcto y estén actualizadas.
- **Aircall**: Si la petición devuelve 200 pero no se envía el mensaje, revisa la rama `SendMessageV2Error` / `errors` en la respuesta GraphQL.
- **Campos obligatorios**: El CSV debe tener `phone` y `firstname` rellenados para cada fila que quieras enviar.

---

## Licencia

Uso interno. Añade aquí la licencia aplicable (p. ej. MIT / Privado) si procede.
