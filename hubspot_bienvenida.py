# -*- coding: utf-8 -*-


from __future__ import annotations

import csv
import json
import os
import time
from typing import Any, Dict, List

import dotenv
import pandas as pd
import requests

# Cargar .env desde la raíz del repo (funciona aunque ejecutes desde scripts/)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_root_dir = os.path.dirname(_script_dir)
dotenv.load_dotenv(os.path.join(_root_dir, ".env"))

# -----------------------------------------------------------------------------
# Configuración compartida (.env)
# -----------------------------------------------------------------------------
CSV_PATH = os.environ.get("CSV_PATH", "data/data.csv")
BATCH_SIZE = int(os.environ.get("HUBSPOT_BATCH_SIZE", "5"))

# -----------------------------------------------------------------------------
# 1) OBTENER REGISTROS (HubSpot → CSV)
# -----------------------------------------------------------------------------

ORIGIN = os.environ.get("HUBSPOT_ORIGIN", "https://app-eu1.hubspot.com")
USER_AGENT = os.environ.get(
    "HUBSPOT_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36",
)
PORTAL_ID = os.environ.get("HUBSPOT_PORTAL_ID", "145440460")
STATIC_APP_VERSION = os.environ.get("HUBSPOT_STATIC_APP_VERSION", "2.50953")
COOKIE_STRING = os.environ.get("HUBSPOT_COOKIE", "")

GRAPHQL_URL = f"{ORIGIN}/api/graphql/crm"
GRAPHQL_PARAMS = {
    "portalId": PORTAL_ID,
    "clienttimeout": "14000",
    "hs_static_app": "crm-index-ui",
    "hs_static_app_version": STATIC_APP_VERSION,
}

IMPORTANT_FIELDS = [
    "hs_object_id", "firstname", "lastname", "email", "phone", "nif", "nif_expiricy",
    "nie_soporte", "aeat_505", "iban_digits", "date_of_birth", "aeat_reference",
]

GQL_QUERY = (
    "query CrmIndexSearchQuery($filterGroups: [FilterGroup!]!, $sorts: [Sort!], $query: String, "
    "$objectTypeId: String!, $properties: [String!]!, $count: Int, $offset: Int) {"
    "  crmObjectsSearch(filterGroups: $filterGroups, sorts: $sorts, query: $query, type: $objectTypeId, count: $count, offset: $offset) {"
    "    total offset results { ...CrmObjectFragment __typename } validationErrors { __typename ... on GenericValidationError { message __typename } } __typename"
    "  }"
    "}"
    "fragment CrmObjectFragment on CrmObject {"
    "  id objectId: id properties(names: $properties) { id name value __typename }"
    "  userPermissions { currentUserCanEdit currentUserCanDelete __typename } __typename"
    "}"
)


def parse_cookie_string(cookie_str: str) -> Dict[str, str]:
    cookies = {}
    for part in [p.strip() for p in cookie_str.split(";") if p.strip()]:
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


def build_session_for_app() -> requests.Session:
    sess = requests.Session()
    cookies = parse_cookie_string(COOKIE_STRING)
    for k, v in cookies.items():
        sess.cookies.set(k, v, domain="app-eu1.hubspot.com")
    csrf = cookies.get("hubspotapi-csrf") or cookies.get("csrf.app")
    if not csrf:
        print("[WARN] No se encontró CSRF en cookies. Esto causará 401.")
    base_headers = {
        "accept-language": "es-ES,es;q=0.9,en;q=0.8",
        "user-agent": USER_AGENT,
        "sec-ch-ua": '"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }
    if csrf:
        base_headers["x-hubspot-csrf-hubspotapi"] = csrf
    sess.headers.update(base_headers)
    return sess


def build_graphql_body(offset: int = 0, count: int = 50, fields: List[str] = None) -> Dict[str, Any]:
    return {
        "operationName": "CrmIndexSearchQuery",
        "variables": {
            "count": count,
            "filterGroups": [{
                "filters": [
                    {"operator": "NOT_IN", "property": "acquisition_channel", "values": ["LABORAI_WHATSAPP_2025"]},
                    {"operator": "NOT_HAS_PROPERTY", "property": "last_aircall_whatsapp_message_timestamp"},
                    {"operator": "GT", "property": "createdate", "value": "2025-12-01", "dateTimeFormat": "DATE"},
                    {"operator": "IN", "property": "hubspot_owner_id", "values": ["76484327"]},
                    {"operator": "IN", "property": "hs_lead_status", "values": ["IN_PROGRESS_LABORAI"]},
                    {"operator": "IN", "property": "query_type", "values": ["reclama"]},
                    {"operator": "IN", "property": "lifecyclestage", "values": ["customer", "lead"]},
                    {"operator": "EQ", "property": "aeat_reference", "value": "ERROR"},
                ]
            }],
            "objectTypeId": "0-1",
            "offset": offset,
            "properties": fields or IMPORTANT_FIELDS,
            "query": "",
            "sorts": [
                {"property": "createdate", "order": "ASC"},
                {"property": "hs_object_id", "order": "DESC"},
            ],
        },
        "query": GQL_QUERY,
    }


def crm_graphql_search(
    sess: requests.Session,
    offset: int = 0,
    count: int = 50,
    fields: List[str] = None,
) -> Dict[str, Any]:
    payload = build_graphql_body(offset=offset, count=count, fields=fields)
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "content-type": "application/json",
        "origin": ORIGIN,
        "referer": f"{ORIGIN}/contacts/{PORTAL_ID}/objects/0-1/views/all/list",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "priority": "u=1, i",
        "accept-encoding": "gzip, deflate, br, zstd",
    }
    r = sess.post(GRAPHQL_URL, params=GRAPHQL_PARAMS, json=payload, headers=headers, timeout=30)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"status": r.status_code, "data": data}


def run_obtener_registros(csv_file: str, batch_size: int = 5, limit_records: int = 50) -> None:
    """Exporta contactos desde HubSpot CRM (GraphQL) a CSV."""
    sess = build_session_for_app()
    os.makedirs(os.path.dirname(csv_file) or ".", exist_ok=True)

    with open(csv_file, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=IMPORTANT_FIELDS)
        writer.writeheader()
        total_exported = 0
        offset = 0

        while True:
            if limit_records and total_exported >= limit_records:
                print(f"Se alcanzó el límite de {limit_records} registros. Exportación completa.")
                break
            print(f">>> Consultando offset {offset}...")
            res = crm_graphql_search(sess, offset=offset, count=batch_size, fields=IMPORTANT_FIELDS)
            data = res.get("data", {})
            results = (data.get("data", {}).get("crmObjectsSearch", {}) or {}).get("results", [])
            if not results:
                print("No hay más resultados. Exportación completa.")
                break
            for record in results:
                props = {p.get("name"): p.get("value") for p in record.get("properties", [])}
                filtered = {k: props.get(k) for k in IMPORTANT_FIELDS}
                writer.writerow(filtered)
            total_exported += len(results)
            offset += batch_size
            print(f"Total exportado: {total_exported}")

    print(f"\nExportación completada. Archivo: {csv_file}")


# -----------------------------------------------------------------------------
# 2) ENVÍO BIENVENIDA (Aircall WhatsApp)
# -----------------------------------------------------------------------------

# Aircall: valores por defecto (se pueden sobrescribir con .env)
AUTH_TOKEN = os.environ.get("AIRCALL_AUTH_TOKEN")
ORIGIN_AIRCALL = os.environ.get("AIRCALL_ORIGIN", "https://app.aircall.io")
CHANNEL = os.environ.get("AIRCALL_CHANNEL", "WHATSAPP")
LINE_ID = os.environ.get("AIRCALL_LINE_ID", "994125")
TEMPLATE_ID = os.environ.get("AIRCALL_TEMPLATE_ID", "2767")
AGENT_NAME = os.environ.get("AIRCALL_AGENT_NAME", "Mar")

# ID del agente según nombre (se usa al asignar conversaciones)
AGENT_IDS = {
    "Silvia": "1784526",
    "Mar": "1805384",
    "Andrea": "1827862",
    "Miguel": "1597886",
}


def _resolve_agent_id(agent_name: str) -> str:
    """Devuelve el AGENT_ID para el nombre dado, o el de .env si no está en el mapa."""
    name = (agent_name or "").strip()
    if name in AGENT_IDS:
        return AGENT_IDS[name]
    return os.environ.get("AIRCALL_AGENT_ID", "1784489")

GRAPHQL_SEND_URL = "https://app.aircall.io/graphql?name=sendMessage_Mutation"
GRAPHQL_CONVERSATIONS_URL = "https://app.aircall.io/graphql?name=ConversationsList_Query"
GRAPHQL_SUBSCRIBE_URL = "https://app.aircall.io/graphql?name=assignConversation_Mutation"

GQL_SEND_QUERY = """mutation sendMessage_Mutation($input: SendMessageV2Input!) {
  sendMessageV2(input: $input) {
    ... on SendMessageV2Output {
      channel messageID direction status text
      mediaDetails { url fileName __typename }
      __typename
    }
    ... on SendMessageV2Error {
      code limitType message __typename
    }
    ...GenericExceptionFragment
    __typename
  }
}
fragment GenericExceptionFragment on GenericException { __typename code message }"""

GQL_QUERY_LIST_CONVERSATIONS = """
query ConversationsList_Query($filters: AircallWorkspaceConversationsFilters, $pageRequest: AircallWorkspaceConversationsPageRequest) {
  getAircallWorkspaceConversations(filters: $filters, pageRequest: $pageRequest) {
    __typename
    ... on PaginatedConversations {
      pageInfo { nextToken }
      items {
        ID
        externalNumber { phoneNumber }
        line { entity { ID name } }
        lastMessageAt
        lastWhatsappAt
        lastEngagementAt
      }
    }
  }
}
"""

GQL_MUTATION_ASSIGN_CONV = """
mutation assignConversation_Mutation($ID: ID!, $agentID: ID!) {
  assignAircallWorkspaceConversation(ID: $ID, agentID: $agentID) {
    __typename
    ... on AircallWorkspaceConversation { ID __typename }
    ... on GenericException { code message __typename }
  }
}
"""


def _aircall_headers() -> Dict[str, str]:
    if not AUTH_TOKEN:
        raise ValueError("Falta AIRCALL_AUTH_TOKEN")
    return {
        "accept": "*/*",
        "content-type": "application/json",
        "authorization": AUTH_TOKEN,
        "origin": "https://app.aircall.io",
        "referer": ORIGIN_AIRCALL + "/workspace/conversations",
    }


def normalizar_numero(numero: str) -> str:
    return "".join(ch for ch in (numero or "") if ch.isdigit())


def send_whatsapp_template(external_number: str, nombre: str, agente: str, mensaje: str) -> Dict[str, Any]:
    """Envía plantilla de bienvenida (nombre, agente, mensaje)."""
    payload = {
        "operationName": "sendMessage_Mutation",
        "variables": {
            "input": {
                "text": "",
                "mediaKeys": [],
                "lineID": LINE_ID,
                "externalNumber": external_number,
                "channel": CHANNEL,
                "templateParams": {
                    "id": TEMPLATE_ID,
                    "body": [
                        {"key": "{{1}}", "value": nombre},
                        {"key": "{{2}}", "value": agente},
                        {"key": "{{3}}", "value": mensaje},
                    ],
                },
            }
        },
        "query": GQL_SEND_QUERY,
    }
    r = requests.post(GRAPHQL_SEND_URL, headers=_aircall_headers(), data=json.dumps(payload), timeout=30)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    return {"status": r.status_code, "data": data}


def filter_by_phone(data: dict, target_phone: str) -> List[str]:
    target_norm = normalizar_numero(target_phone)
    items = (
        (data.get("data", {}) or {})
        .get("getAircallWorkspaceConversations", {})
        .get("items", [])
    )
    return [
        it.get("ID")
        for it in (items or [])
        if normalizar_numero((it.get("externalNumber") or {}).get("phoneNumber") or "") == target_norm
    ]


def fetch_conversations(telefono: str) -> Any:
    variables = {
        "filters": {"status": {"in": ["OPENED"]}},
        "pageRequest": {"limit": 10, "sort": "desc"},
    }
    payload = {
        "operationName": "ConversationsList_Query",
        "query": GQL_QUERY_LIST_CONVERSATIONS,
        "variables": variables,
    }
    r = requests.post(GRAPHQL_CONVERSATIONS_URL, headers=_aircall_headers(), data=json.dumps(payload), timeout=30)
    if r.status_code == 200:
        return filter_by_phone(r.json(), telefono)
    return {"error": f"HTTP {r.status_code}", "raw": r.text}


def subscribe_contact(conv_id: Any, agent_id: str | None = None) -> Dict[str, Any]:
    aid = agent_id or _resolve_agent_id(AGENT_NAME)
    cid = conv_id[0] if isinstance(conv_id, list) and len(conv_id) > 0 else None
    if not cid:
        return {"status": None, "error": "No conversation ID found to assign.", "resolved_conversation_id": None}
    payload = {
        "operationName": "assignConversation_Mutation",
        "query": GQL_MUTATION_ASSIGN_CONV,
        "variables": {"ID": cid, "agentID": aid},
    }
    try:
        r = requests.post(GRAPHQL_SUBSCRIBE_URL, headers=_aircall_headers(), data=json.dumps(payload), timeout=30)
        try:
            data = r.json()
        except Exception:
            data = {"raw": r.text}
        return {"status": r.status_code, "data": data, "resolved_conversation_id": cid}
    except requests.RequestException as e:
        return {"status": None, "error": str(e), "resolved_conversation_id": cid}


def build_mensaje(row: pd.Series) -> str:
    """Construye el mensaje según casilla 505 / NIF / NIE (igual que el notebook)."""
    nif = (row.get("nif") or "").strip()
    fecha_validez = (row.get("nif_expiricy") or "").strip()
    soporte = (row.get("nie_soporte") or "").strip()
    casilla_505 = (row.get("aeat_505") or "").strip()

    if casilla_505:
        if nif and fecha_validez:
            return (
                "porque tras intentar verificar tu perfil con la Agencia Tributaria, nos consta que alguno de los datos proporcionados no es correcto: "
                f"- NIF: {nif} - Fecha de validez: {fecha_validez} - Casilla 505: {casilla_505} "
                "(Asegúrate por favor que la declaración sea del Ejercicio 2023)  Por favor verifica estos datos nuevamente. Quedamos a la espera, muchas gracias!"
            )
        elif nif and soporte:
            return (
                "porque tras intentar verificar tu perfil con la Agencia Tributaria, nos consta que alguno de los datos proporcionados no es correcto: "
                f"- NIE: {nif} - Número de soporte: {soporte} - Casilla 505: {casilla_505} "
                "(Asegúrate por favor que la declaración sea del Ejercicio 2023). Por favor verifica estos datos nuevamente. Quedamos a la espera, muchas gracias!"
            )
        else:
            return (
                "porque tras intentar verificar tu perfil con la Agencia Tributaria, nos consta que alguno de los datos proporcionados no es correcto. "
                "Necesitamos que nos envíes tu DNI/Fecha de validez o NIE/Numero de soporte. Por favor verifica estos datos nuevamente. Quedamos a la espera, muchas gracias!"
            )
    else:
        return (
            "porque para poder revisar tus declaraciones de la renta pasadas, necesitamos adicionalmente "
            "el valor de la casilla 505 del ejercicio 2023. Quedamos a la espera, muchas gracias!"
        )


def run_envio_bienvenida(
    csv_path: str,
    agent_name: str | None = None,
    cantidad: int = 0,
) -> None:
    """Lee CSV, envía plantilla de bienvenida por Aircall y asigna conversación al agente."""
    if not all([AUTH_TOKEN, LINE_ID, CHANNEL, TEMPLATE_ID]):
        raise ValueError("Faltan variables AIRCALL: AUTH_TOKEN, LINE_ID, CHANNEL, TEMPLATE_ID")

    nombre_agente = (agent_name or "").strip() or AGENT_NAME
    agent_id = _resolve_agent_id(nombre_agente)

    df = pd.read_csv(csv_path, dtype=str, encoding="utf-8")
    for col in ["phone", "firstname", "nif", "nif_expiricy", "nie_soporte", "aeat_505", "iban_digits"]:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(str).str.strip()

    df["nif_expiricy"] = pd.to_numeric(df["nif_expiricy"], errors="coerce")
    df["nif_expiricy"] = pd.to_datetime(df["nif_expiricy"], unit="ms").dt.strftime("%Y-%m-%d")
    df = df.fillna("")

    missing_required = df[(df["phone"] == "") | (df["firstname"] == "")]
    if not missing_required.empty:
        print("Filas con campos obligatorios vacíos:")
        print(missing_required)
        raise ValueError("Revisa los campos obligatorios: phone, firstname")

    if cantidad > 0:
        df = df.head(cantidad)
    print(f"CSV leído: {len(df)} filas (agente: {nombre_agente})")

    for index, row in df.iterrows():
        telefono_cliente = row["phone"]
        nombre_cliente = row["firstname"]
        mensaje = build_mensaje(row)

        print(f"\n=== Fila {index + 1}: Enviando a {nombre_cliente} ({telefono_cliente}) ===")
        print(">>> Enviando WhatsApp…")
        resp_send = send_whatsapp_template(telefono_cliente, nombre_cliente, nombre_agente, mensaje)
        if resp_send["status"] != 200:
            print(f"Error en envío: HTTP {resp_send['status']}")
            print(resp_send.get("data", {}))
        else:
            print("Envío realizado con éxito.")
            df = df.drop(index=index)

        time.sleep(0.5)
        print(">>> Buscando conversación abierta no asignada…")
        resp_conv = fetch_conversations(telefono_cliente)
        if isinstance(resp_conv, dict) and resp_conv.get("error"):
            print(f"Error al buscar conversación: {resp_conv}")
            continue
        print(">>> Suscribiendo contacto…")
        subscribe_contact(resp_conv, agent_id=agent_id)

    print("\nProceso finalizado.")


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------

def _pedir_nombre_agente() -> str:
    valor = input("Nombre de agente: ").strip()
    return valor or os.environ.get("AIRCALL_AGENT_NAME", "Automático")


def _pedir_cantidad() -> int:
    valor = input("Cantidad (vacío = todos/sin límite): ").strip()
    if not valor:
        return 0
    try:
        return max(0, int(valor))
    except ValueError:
        return 0


def main() -> None:
    # 1) Obtener registros desde HubSpot → CSV
    cantidad = _pedir_cantidad()
    nombre_agente = _pedir_nombre_agente()

    if cantidad > 0:
        print(f"Exportando hasta {cantidad} registros a {CSV_PATH}")
    else:
        print(f"Exportando registros a {CSV_PATH} (sin límite)")
    run_obtener_registros(CSV_PATH, batch_size=BATCH_SIZE, limit_records=cantidad or None)

    # 2) Envío de bienvenida (Aircall WhatsApp)
    print(f"Enviando hasta {cantidad} mensajes. Agente: {nombre_agente}")
    run_envio_bienvenida(CSV_PATH, agent_name=nombre_agente, cantidad=cantidad)


if __name__ == "__main__":
    main()
