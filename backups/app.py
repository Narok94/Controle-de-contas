"""
Organizador de Contas - Versão Melhorada
Melhorias implementadas:
 - Validações mais robustas
 - Notificações de vencimento
 - Dashboard melhorado com alertas
 - Histórico de alterações
 - Exportação de dados
 - Modo escuro/claro
 - Confirmações de segurança
 - Gráfico de colunas por categoria
Compatível com Python 3.13 + Flask 3.1.2
"""
from flask import Flask, request, redirect, url_for, flash, render_template_string, jsonify, send_file
import json
import os
import uuid
import calendar
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, date, timedelta
import threading
import hashlib
import zipfile
import io

app = Flask(__name__)
app.secret_key = "troque_essa_chave_para_uma_aleatoria_mais_segura_2024"

# ---------- Config ----------
DATA_FILE = "dados.json"
HISTORY_FILE = "historico.json"
DATA_LOCK = threading.Lock()

FIXED_CATEGORIES = [
    {"name": "Luz", "icon": "💡"},
    {"name": "Água", "icon": "💧"},
    {"name": "Internet", "icon": "🌐"},
    {"name": "Mercado", "icon": "🛒"},
    {"name": "Cartão", "icon": "💳"},
    {"name": "Manuela", "icon": "👸"},
]
DEFAULT_EXTRA = {"name": "Outros", "icon": "🧾"}

# ---------- Histórico ----------
def log_action(action, details):
    """Registra ações no histórico"""
    try:
        history = []
        if os.path.exists(HISTORY_FILE):
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        
        history.append({
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details
        })
        
        # Manter apenas os últimos 100 registros
        history = history[-100:]
        
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception:
        pass  # Não falhar se não conseguir logar

# ---------- Persistência ----------
def _ensure_datafile():
    if not os.path.exists(DATA_FILE):
        base = {
            "contas": [], 
            "categories": FIXED_CATEGORIES + [DEFAULT_EXTRA],
            "settings": {
                "theme": "light",
                "notifications_enabled": True,
                "days_alert_before_due": 3
            }
        }
        with DATA_LOCK:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(base, f, ensure_ascii=False, indent=2)

def load_data():
    _ensure_datafile()
    with DATA_LOCK:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except Exception:
                data = {
                    "contas": [], 
                    "categories": FIXED_CATEGORIES + [DEFAULT_EXTRA],
                    "settings": {
                        "theme": "light",
                        "notifications_enabled": True,
                        "days_alert_before_due": 3
                    }
                }
    
    # Garantir que settings existe
    if "settings" not in data:
        data["settings"] = {
            "theme": "light",
            "notifications_enabled": True,
            "days_alert_before_due": 3
        }
    
    # normalizar categorias: garantir que as fixas existam primeiro
    cats = data.get("categories", [])
    normalized = []
    seen = set()
    for fc in FIXED_CATEGORIES + [DEFAULT_EXTRA]:
        name = fc.get("name")
        normalized.append({"name": name, "icon": fc.get("icon", "📂")})
        seen.add(name)
    for c in cats:
        if isinstance(c, dict):
            name = c.get("name") or str(c)
            icon = c.get("icon") or "📂"
        else:
            name = str(c)
            icon = "📂"
        if name in seen:
            continue
        normalized.append({"name": name, "icon": icon})
        seen.add(name)
    data["categories"] = normalized

    # normalizar contas
    contas = data.get("contas", [])
    for c in contas:
        if "id" not in c:
            c["id"] = str(uuid.uuid4())
        if "name" not in c:
            c["name"] = c.get("title") or "Sem título"
        if "amount_decimal" not in c:
            c["amount_decimal"] = str(c.get("valor") or c.get("value") or "0.00")
        if "status" not in c:
            c["status"] = "pending"
        if "month" not in c:
            if c.get("created_at"):
                try:
                    dt = datetime.fromisoformat(c["created_at"])
                    c["month"] = dt.strftime("%Y-%m")
                except Exception:
                    c["month"] = date.today().strftime("%Y-%m")
            else:
                c["month"] = date.today().strftime("%Y-%m")
        if "due_date" not in c:
            # Adicionar data de vencimento baseada no mês
            try:
                year, month = map(int, c["month"].split("-"))
                c["due_date"] = date(year, month, 15).isoformat()  # Default: dia 15
            except Exception:
                c["due_date"] = date.today().isoformat()
        if "recorrente" not in c:
            c["recorrente"] = bool(c.get("rec_type") in ("fixed", "indef") or int(c.get("recorrencia_months", 0) or 0) > 0)
        if "recorrencia_months" not in c:
            try:
                c["recorrencia_months"] = int(c.get("recorrencia_months", 0) or 0)
            except Exception:
                c["recorrencia_months"] = 0
        if "rec_type" not in c:
            c["rec_type"] = c.get("rec_type", None)
        if "parcelada" not in c:
            c["parcelada"] = bool(int(c.get("parcelas", 1) or 1) > 1)
        if "parcelas" not in c:
            try:
                c["parcelas"] = int(c.get("parcelas", 1) or 1)
            except Exception:
                c["parcelas"] = 1
        if "priority" not in c:
            c["priority"] = "normal"  # low, normal, high, urgent
    data["contas"] = contas
    return data

def save_data(data):
    with DATA_LOCK:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

# ---------- Utilitários ----------
def money_to_decimal(value_str):
    if value_str is None:
        raise InvalidOperation
    v = str(value_str).strip()
    v = v.replace(" ", "")
    # aceita 1.234,56 ou 1234,56 ou 1234.56
    v = v.replace(".", "").replace(",", ".")
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def decimal_to_brl(d):
    try:
        d = Decimal(d)
        q = f"{d:,.2f}"
    except Exception:
        q = "0,00"
    q = q.replace(",", "X").replace(".", ",").replace("X", ".")
    return "R$ " + q

def month_key_from_date(dt: date):
    return dt.strftime("%Y-%m")

def parse_month_input(s):
    if not s:
        return None
    try:
        parts = s.split("-")
        y = int(parts[0]); m = int(parts[1])
        return date(y, m, 1)
    except Exception:
        return None

def add_months(sourcedate: date, months: int) -> date:
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

def split_amount_into_installments(amount: Decimal, n: int):
    if n <= 1:
        return [amount.quantize(Decimal("0.01"))]
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    base = (amount / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    parts = [base for _ in range(n)]
    total_parts = sum(parts)
    diff = amount - total_parts
    parts[-1] = (parts[-1] + diff).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return parts

def color_for_category(name):
    # cor determinística por nome
    h = int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16)
    hue = h % 360
    sat = 60
    light = 55
    return hsl_to_hex(hue, sat, light)

def hsl_to_hex(h, s, l):
    s /= 100.0
    l /= 100.0
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = l - c/2
    if h < 60:
        r1,g1,b1 = c,x,0
    elif h < 120:
        r1,g1,b1 = x,c,0
    elif h < 180:
        r1,g1,b1 = 0,c,x
    elif h < 240:
        r1,g1,b1 = 0,x,c
    elif h < 300:
        r1,g1,b1 = x,0,c
    else:
        r1,g1,b1 = c,0,x
    r = int((r1 + m) * 255)
    g = int((g1 + m) * 255)
    b = int((b1 + m) * 255)
    return '#{:02x}{:02x}{:02x}'.format(r,g,b)

def get_due_alerts(contas, days_ahead=3):
    """Retorna contas que vencem nos próximos X dias"""
    alerts = []
    today = date.today()
    alert_date = today + timedelta(days=days_ahead)
    
    for conta in contas:
        if conta.get("status") == "paid":
            continue
            
        try:
            due_date = date.fromisoformat(conta.get("due_date", ""))
            if today <= due_date <= alert_date:
                days_until = (due_date - today).days
                alerts.append({
                    "conta": conta,
                    "days_until": days_until,
                    "is_overdue": due_date < today,
                    "is_today": due_date == today
                })
        except Exception:
            continue
    
    return sorted(alerts, key=lambda x: x["days_until"])

# ---------- Recorrência automática ----------
def ensure_recurring_for_month(data, month_key):
    """
    Gera instâncias recorrentes para month_key automaticamente.
    - rec_type 'indef' -> próxima fatura com valor 0 (se não existir)
    - rec_type 'fixed' -> gera cópias até rec_months, copiando valor do mês anterior
    """
    contas = data.setdefault("contas", [])
    origins = [c for c in contas if c.get("rec_type") in ("indef", "fixed") and not c.get("rec_origin")]
    for origin in origins:
        origin_id = origin.get("id")
        rec_type = origin.get("rec_type")
        rec_months = int(origin.get("recorrencia_months", 0) or 0)
        # se target < origin, pular
        try:
            oy, om = map(int, (origin.get("month") or "0000-00").split("-"))
            odate = date(oy, om, 1)
            ty, tm = map(int, month_key.split("-"))
            tdate = date(ty, tm, 1)
            if tdate < odate:
                continue
        except Exception:
            pass

        # evitar duplicatas
        exists = any(
            (cc.get("month") == month_key) and (
                cc.get("rec_origin") == origin_id or cc.get("origin") == origin_id or cc.get("name") == origin.get("name")
            )
            for cc in contas
        )
        if exists:
            continue

        if rec_type == "indef":
            # Calcular data de vencimento para o novo mês
            try:
                orig_due = date.fromisoformat(origin.get("due_date", ""))
                new_due = date(ty, tm, orig_due.day)
            except Exception:
                new_due = date(ty, tm, 15)
            
            inst = {
                "id": str(uuid.uuid4()),
                "name": origin.get("name"),
                "amount_decimal": str(Decimal("0.00")),
                "amount_display": str(Decimal("0.00")),
                "month": month_key,
                "due_date": new_due.isoformat(),
                "category": origin.get("category"),
                "notes": origin.get("notes"),
                "status": "pending",
                "paid_at": None,
                "paid_amount": None,
                "created_at": datetime.now().isoformat(),
                "recorrente": True,
                "rec_type": "indef",
                "recorrencia_months": 0,
                "rec_origin": origin_id,
                "parcelada": False,
                "parcelas": 1,
                "priority": origin.get("priority", "normal")
            }
            contas.append(inst)
        elif rec_type == "fixed" and rec_months > 0:
            # calcular offset em meses desde origem
            try:
                oy, om = map(int, (origin.get("month") or "0000-00").split("-"))
                odate = date(oy, om, 1)
                ty, tm = map(int, month_key.split("-"))
                tdate = date(ty, tm, 1)
                months_offset = (tdate.year - odate.year) * 12 + (tdate.month - odate.month)
            except Exception:
                months_offset = 0
            if months_offset < rec_months:
                # pegar valor do mês anterior
                prev_date = add_months(tdate, -1)
                prev_key = month_key_from_date(prev_date)
                prev_inst = None
                for cc in contas:
                    if cc.get("month") == prev_key and (
                        cc.get("rec_origin") == origin_id or cc.get("origin") == origin_id or cc.get("name") == origin.get("name")
                    ):
                        prev_inst = cc
                        break
                if prev_inst is None:
                    try:
                        prev_value = Decimal(str(origin.get("amount_decimal", "0")))
                    except Exception:
                        prev_value = Decimal("0")
                else:
                    try:
                        prev_value = Decimal(str(prev_inst.get("amount_decimal", "0")))
                    except Exception:
                        prev_value = Decimal("0")
                
                # Calcular data de vencimento
                try:
                    orig_due = date.fromisoformat(origin.get("due_date", ""))
                    new_due = date(ty, tm, orig_due.day)
                except Exception:
                    new_due = date(ty, tm, 15)
                
                inst = {
                    "id": str(uuid.uuid4()),
                    "name": origin.get("name"),
                    "amount_decimal": str(prev_value.quantize(Decimal("0.01"))),
                    "amount_display": str(prev_value),
                    "month": month_key,
                    "due_date": new_due.isoformat(),
                    "category": origin.get("category"),
                    "notes": origin.get("notes"),
                    "status": "pending",
                    "paid_at": None,
                    "paid_amount": None,
                    "created_at": datetime.now().isoformat(),
                    "recorrente": True,
                    "rec_type": "fixed",
                    "recorrencia_months": rec_months,
                    "rec_origin": origin_id,
                    "parcelada": False,
                    "parcelas": 1,
                    "priority": origin.get("priority", "normal")
                }
                contas.append(inst)

# Garantir recorrências para o mês atual ao iniciar
try:
    data_tmp = load_data()
    ensure_recurring_for_month(data_tmp, date.today().strftime("%Y-%m"))
    save_data(data_tmp)
except Exception:
    pass

# ---------- Rotas ----------
@app.route("/", methods=["GET"])
def index():
    data = load_data()
    contas = data.get("contas", [])
    categories = data.get("categories", FIXED_CATEGORIES + [DEFAULT_EXTRA])
    settings = data.get("settings", {})

    sel_month = request.args.get("month") or date.today().strftime("%Y-%m")
    sel_category = request.args.get("category") or "Todos"
    q_search = (request.args.get("q") or "").strip().lower()

    # gerar recorrências automaticamente para o mês solicitado e para o mês atual
    try:
        ensure_recurring_for_month(data, sel_month)
        ensure_recurring_for_month(data, date.today().strftime("%Y-%m"))
        save_data(data)
    except Exception:
        pass

    # recarregar
    data = load_data()
    contas = data.get("contas", [])
    categories = data.get("categories", FIXED_CATEGORIES + [DEFAULT_EXTRA])

    # filtrar contas do mês selecionado
    contas_mes = [c for c in contas if c.get("month") == sel_month]
    if sel_category and sel_category != "Todos":
        contas_mes = [c for c in contas_mes if c.get("category") == sel_category]
    if q_search:
        contas_mes = [c for c in contas_mes if q_search in ((c.get("name","") + " " + c.get("notes","")).lower())]
    
    # Ordenar por prioridade e data de vencimento
    priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    contas_mes.sort(key=lambda c: (
        priority_order.get(c.get("priority", "normal"), 2),
        c.get("due_date", ""),
        c.get("created_at") or "",
        c.get("name", "")
    ))

    def totals_for_month(month_key):
        total = Decimal("0")
        paid = Decimal("0")
        pending = Decimal("0")
        overdue = Decimal("0")
        by_cat = {cat.get("name"): Decimal("0") for cat in categories}
        by_cat["Outros"] = by_cat.get("Outros", Decimal("0"))
        
        today = date.today()
        
        for c in contas:
            if c.get("month") == month_key:
                try:
                    val = Decimal(str(c.get("amount_decimal","0")))
                except Exception:
                    val = Decimal("0")
                total += val
                cat = c.get("category") or "Outros"
                if cat not in by_cat:
                    by_cat[cat] = Decimal("0")
                by_cat[cat] += val
                
                if c.get("status") == "paid":
                    paid_amount = c.get("paid_amount")
                    if paid_amount:
                        try:
                            paid += Decimal(str(paid_amount))
                        except Exception:
                            paid += val
                    else:
                        paid += val
                else:
                    pending += val
                    # Verificar se está vencida
                    try:
                        due_date = date.fromisoformat(c.get("due_date", ""))
                        if due_date < today:
                            overdue += val
                    except Exception:
                        pass
        
        return {"total": total, "paid": paid, "pending": pending, "overdue": overdue, "by_category": by_cat}

    curr_totals = totals_for_month(sel_month)
    try:
        y, m = map(int, sel_month.split("-"))
        prev_dt = add_months(date(y, m, 1), -1)
        prev_month_key = month_key_from_date(prev_dt)
    except Exception:
        prev_month_key = None
    prev_totals = totals_for_month(prev_month_key) if prev_month_key else {"total": Decimal("0"), "paid": Decimal("0"), "pending": Decimal("0"), "overdue": Decimal("0"), "by_category": {}}

    diff = curr_totals["total"] - prev_totals["total"]
    percent = None
    try:
        if prev_totals["total"] != Decimal("0"):
            percent = (diff / prev_totals["total"]) * 100
            percent = percent.quantize(Decimal("0.1"))
    except Exception:
        percent = None

    months = sorted({c.get("month") for c in contas if c.get("month")} | {date.today().strftime("%Y-%m")}, reverse=True)

    cat_colors = {c.get("name"): color_for_category(c.get("name")) for c in categories}
    cat_colors["Outros"] = color_for_category("Outros")

    # Alertas de vencimento
    alerts = []
    if settings.get("notifications_enabled", True):
        days_ahead = settings.get("days_alert_before_due", 3)
        alerts = get_due_alerts(contas, days_ahead)

    # Adicionar data atual para o template
    today_str = date.today().isoformat()

    return render_template_string(TEMPLATE_INDEX,
        contas=contas_mes,
        sel_month=sel_month,
        months=months,
        categories=["Todos"] + [c.get("name") for c in categories],
        categories_full=categories,
        sel_category=sel_category,
        q_search=q_search,
        curr_totals=curr_totals,
        prev_totals=prev_totals,
        prev_month_key=prev_month_key,
        diff=diff,
        percent=percent,
        decimal_to_brl=decimal_to_brl,
        cat_colors=cat_colors,
        alerts=alerts,
        settings=settings,
        today=today_str
    )

@app.route("/cadastrar", methods=["GET", "POST"])
def cadastrar():
    data = load_data()
    categories = data.get("categories", FIXED_CATEGORIES + [DEFAULT_EXTRA])
    if request.method == "POST":
        name = request.form.get("name","").strip()
        valor_raw = request.form.get("value","").strip()
        mes_input = request.form.get("mes") or date.today().strftime("%Y-%m")
        due_date_input = request.form.get("due_date") or ""
        category = request.form.get("category") or "Outros"
        notes = request.form.get("notes","").strip()
        priority = request.form.get("priority") or "normal"

        recorr_indef = True if request.form.get("recorrente_indef") == "on" else False
        try:
            recorrencia_months = int(request.form.get("recorrencia_months") or 0)
            if recorrencia_months < 0:
                recorrencia_months = 0
        except Exception:
            recorrencia_months = 0

        parcelada = True if request.form.get("parcelada") == "on" else False
        try:
            parcelas = int(request.form.get("parcelas") or 1)
            if parcelas < 1:
                parcelas = 1
        except Exception:
            parcelas = 1

        # Validações mais robustas
        if not name:
            flash("Nome da conta é obrigatório.", "danger")
            return redirect(url_for("cadastrar"))

        # valida valor no submit (campo sem máscara)
        try:
            value = money_to_decimal(valor_raw)
            if value < 0:
                flash("Valor não pode ser negativo.", "danger")
                return redirect(url_for("cadastrar"))
        except Exception:
            flash("Valor inválido. Use formato numérico (ex: 150,50 ou 150.50).", "danger")
            return redirect(url_for("cadastrar"))

        mes_date = parse_month_input(mes_input)
        if not mes_date:
            flash("Mês inválido.", "danger")
            return redirect(url_for("cadastrar"))
        month_key = month_key_from_date(mes_date)

        # Validar data de vencimento
        if due_date_input:
            try:
                due_date = date.fromisoformat(due_date_input)
            except Exception:
                flash("Data de vencimento inválida.", "danger")
                return redirect(url_for("cadastrar"))
        else:
            # Default: dia 15 do mês
            due_date = date(mes_date.year, mes_date.month, 15)

        rec_type = None
        if recorr_indef:
            rec_type = "indef"
        elif recorrencia_months and recorrencia_months > 0:
            rec_type = "fixed"

        base = {
            "id": str(uuid.uuid4()),
            "name": name,
            "amount_decimal": str(value.quantize(Decimal("0.01"))),
            "amount_display": str(value),
            "month": month_key,
            "due_date": due_date.isoformat(),
            "category": category,
            "notes": notes,
            "priority": priority,
            "status": "pending",
            "paid_at": None,
            "paid_amount": None,
            "created_at": datetime.now().isoformat(),
            "recorrente": True if rec_type else False,
            "rec_type": rec_type,
            "recorrencia_months": int(recorrencia_months),
            "rec_origin": None,
            "parcelada": bool(parcelada),
            "parcelas": int(parcelas),
            "parcel_index": None,
            "parcel_total": None
        }

        data.setdefault("contas", []).append(base)

        # parcelamento: gerar parcelas futuras
        if parcelada and parcelas > 1:
            parts = split_amount_into_installments(value, parcelas)
            base["amount_decimal"] = str(parts[0].quantize(Decimal("0.01")))
            base["amount_display"] = str(parts[0])
            base["parcel_index"] = 1
            base["parcel_total"] = parcelas
            try:
                start = mes_date
                for i in range(1, parcelas):
                    next_dt = add_months(start, i)
                    next_month_key = month_key_from_date(next_dt)
                    next_due = add_months(due_date, i)
                    inst = {
                        "id": str(uuid.uuid4()),
                        "name": name,
                        "amount_decimal": str(parts[i].quantize(Decimal("0.01"))),
                        "amount_display": str(parts[i]),
                        "month": next_month_key,
                        "due_date": next_due.isoformat(),
                        "category": category,
                        "notes": notes,
                        "priority": priority,
                        "status": "pending",
                        "paid_at": None,
                        "paid_amount": None,
                        "created_at": datetime.now().isoformat(),
                        "recorrente": False,
                        "rec_type": None,
                        "recorrencia_months": 0,
                        "rec_origin": None,
                        "parcelada": True,
                        "parcelas": parcelas,
                        "parcel_index": i+1,
                        "parcel_total": parcelas
                    }
                    data["contas"].append(inst)
            except Exception:
                pass

        # recorrência fixa por X meses (gera cópias mantendo valor atual)
        if rec_type == "fixed" and recorrencia_months > 0:
            origin_id = base.get("id")
            base["rec_origin"] = origin_id
            try:
                start = mes_date
                for i in range(1, recorrencia_months):
                    next_dt = add_months(start, i)
                    next_month_key = month_key_from_date(next_dt)
                    next_due = add_months(due_date, i)
                    inst_val = value.quantize(Decimal("0.01"))
                    inst = {
                        "id": str(uuid.uuid4()),
                        "name": name,
                        "amount_decimal": str(inst_val),
                        "amount_display": str(inst_val),
                        "month": next_month_key,
                        "due_date": next_due.isoformat(),
                        "category": category,
                        "notes": notes,
                        "priority": priority,
                        "status": "pending",
                        "paid_at": None,
                        "paid_amount": None,
                        "created_at": datetime.now().isoformat(),
                        "recorrente": True,
                        "rec_type": "fixed",
                        "recorrencia_months": recorrencia_months,
                        "rec_origin": origin_id,
                        "parcelada": False,
                        "parcelas": 1
                    }
                    data["contas"].append(inst)
            except Exception:
                pass
        elif rec_type == "indef":
            origin_id = base.get("id")
            base["rec_origin"] = origin_id
            try:
                next_dt = add_months(mes_date, 1)
                next_month_key = month_key_from_date(next_dt)
                next_due = add_months(due_date, 1)
                inst = base.copy()
                inst["id"] = str(uuid.uuid4())
                inst["month"] = next_month_key
                inst["due_date"] = next_due.isoformat()
                inst["amount_decimal"] = str(Decimal("0.00"))
                inst["amount_display"] = str(Decimal("0.00"))
                inst["status"] = "pending"
                inst["paid_at"] = None
                inst["paid_amount"] = None
                inst["created_at"] = datetime.now().isoformat()
                inst["recorrente"] = True
                inst["rec_type"] = "indef"
                inst["rec_origin"] = origin_id
                inst["parcelada"] = False
                inst["parcelas"] = 1
                data["contas"].append(inst)
            except Exception:
                pass

        save_data(data)
        log_action("CREATE_CONTA", f"Criada conta: {name} - {decimal_to_brl(value)}")
        flash("Conta cadastrada com sucesso.", "success")
        return redirect(url_for("cadastrar"))

    default_mes = date.today().strftime("%Y-%m")
    empty_form = {
        "id": None,
        "name": "",
        "value": "",
        "mes": default_mes,
        "due_date": "",
        "category": "",
        "notes": "",
        "priority": "normal",
        "recorrente_indef": False,
        "recorrencia_months": 0,
        "parcelada": False,
        "parcelas": 1
    }
    return render_template_string(TEMPLATE_CADASTRAR, categories=categories, form=empty_form)

@app.route("/edit/<id>", methods=["GET", "POST"])
def edit(id):
    data = load_data()
    contas = data.get("contas", [])
    categories = data.get("categories", FIXED_CATEGORIES + [DEFAULT_EXTRA])
    target = next((c for c in contas if c.get("id") == id), None)
    if not target:
        flash("Conta não encontrada.", "danger")
        return redirect(url_for("index"))

    if request.method == "POST":
        name = request.form.get("name","").strip()
        valor_raw = request.form.get("value","").strip()
        mes_input = request.form.get("mes") or target.get("month")
        due_date_input = request.form.get("due_date") or target.get("due_date")
        category = request.form.get("category") or "Outros"
        notes = request.form.get("notes","").strip()
        priority = request.form.get("priority") or "normal"

        recorr_indef = True if request.form.get("recorrente_indef") == "on" else False
        try:
            recorrencia_months = int(request.form.get("recorrencia_months") or 0)
            if recorrencia_months < 0:
                recorrencia_months = 0
        except Exception:
            recorrencia_months = target.get("recorrencia_months", 0)

        parcelada = True if request.form.get("parcelada") == "on" else False
        try:
            parcelas = int(request.form.get("parcelas") or target.get("parcelas", 1))
            if parcelas < 1:
                parcelas = 1
        except Exception:
            parcelas = target.get("parcelas", 1)

        # Validações
        if not name:
            flash("Nome da conta é obrigatório.", "danger")
            return redirect(url_for("edit", id=id))

        try:
            value = money_to_decimal(valor_raw)
            if value < 0:
                flash("Valor não pode ser negativo.", "danger")
                return redirect(url_for("edit", id=id))
        except Exception:
            flash("Valor inválido.", "danger")
            return redirect(url_for("edit", id=id))

        mes_date = parse_month_input(mes_input)
        if not mes_date:
            flash("Mês inválido.", "danger")
            return redirect(url_for("edit", id=id))
        month_key = month_key_from_date(mes_date)

        try:
            due_date = date.fromisoformat(due_date_input)
        except Exception:
            flash("Data de vencimento inválida.", "danger")
            return redirect(url_for("edit", id=id))

        # Guardar valores originais para log
        old_name = target.get("name")
        old_value = target.get("amount_decimal")

        # atualizar campos
        target["name"] = name
        target["amount_decimal"] = str(value.quantize(Decimal("0.01")))
        target["amount_display"] = str(value)
        target["month"] = month_key
        target["due_date"] = due_date.isoformat()
        target["category"] = category
        target["notes"] = notes
        target["priority"] = priority

        if recorr_indef:
            target["recorrente"] = True
            target["rec_type"] = "indef"
            target["recorrencia_months"] = 0
        elif recorrencia_months and recorrencia_months > 0:
            target["recorrente"] = True
            target["rec_type"] = "fixed"
            target["recorrencia_months"] = int(recorrencia_months)
        else:
            target["recorrente"] = False
            target["rec_type"] = None
            target["recorrencia_months"] = 0

        target["parcelada"] = bool(parcelada)
        target["parcelas"] = int(parcelas)
        target["updated_at"] = datetime.now().isoformat()

        save_data(data)
        log_action("UPDATE_CONTA", f"Editada conta: {old_name} -> {name}")
        flash("Conta atualizada com sucesso.", "success")
        return redirect(url_for("index", month=month_key))

    # GET -> preencher form com dados da conta
    form_vals = {
        "id": target.get("id"),
        "name": target.get("name"),
        "value": target.get("amount_decimal"),
        "mes": target.get("month"),
        "due_date": target.get("due_date"),
        "category": target.get("category"),
        "notes": target.get("notes"),
        "priority": target.get("priority", "normal"),
        "recorrente_indef": target.get("rec_type") == "indef",
        "recorrencia_months": target.get("recorrencia_months", 0),
        "parcelada": target.get("parcelada", False),
        "parcelas": target.get("parcelas", 1)
    }
    return render_template_string(TEMPLATE_CADASTRAR, categories=categories, form=form_vals)

@app.route("/toggle_pay/<id>", methods=["POST"])
def toggle_pay(id):
    """
    Se estiver 'paid' -> volta para 'pending' (desfazer).
    Se estiver 'pending' -> marcar como 'paid' (valores podem ser passados no form).
    """
    data = load_data()
    contas = data.get("contas", [])
    target = next((c for c in contas if c.get("id") == id), None)
    if not target:
        flash("Conta não encontrada.", "danger")
        return redirect(url_for("index", month=request.args.get("month") or date.today().strftime("%Y-%m")))

    if target.get("status") == "paid":
        # desfazer pagamento
        target["status"] = "pending"
        target["paid_at"] = None
        target["paid_amount"] = None
        log_action("UNDO_PAYMENT", f"Pagamento desfeito: {target.get('name')}")
        flash("Pagamento desfeito (voltou a pendente).", "info")
    else:
        # marcar como paga
        paid_amount_raw = request.form.get("paid_amount")
        paid_date_raw = request.form.get("paid_date")
        if paid_amount_raw:
            try:
                paid_amount = money_to_decimal(paid_amount_raw)
                if paid_amount < 0:
                    flash("Valor de pagamento não pode ser negativo.", "danger")
                    return redirect(url_for("index", month=request.args.get("month") or target.get("month") or date.today().strftime("%Y-%m")))
                target["paid_amount"] = str(paid_amount)
            except Exception:
                flash("Valor de pagamento inválido.", "danger")
                return redirect(url_for("index", month=request.args.get("month") or target.get("month") or date.today().strftime("%Y-%m")))
        else:
            target["paid_amount"] = target.get("amount_decimal")
        if paid_date_raw:
            try:
                # aceitar YYYY-MM-DD
                target["paid_at"] = datetime.fromisoformat(paid_date_raw).isoformat()
            except Exception:
                target["paid_at"] = datetime.now().isoformat()
        else:
            target["paid_at"] = datetime.now().isoformat()
        target["status"] = "paid"
        log_action("MARK_PAID", f"Conta paga: {target.get('name')} - {decimal_to_brl(target.get('paid_amount', target.get('amount_decimal')))}")
        flash("Conta marcada como paga.", "success")

    save_data(data)
    return redirect(url_for("index", month=request.args.get("month") or target.get("month") or date.today().strftime("%Y-%m")))

@app.route("/delete/<id>", methods=["POST"])
def delete(id):
    data = load_data()
    contas = data.get("contas", [])
    target = next((c for c in contas if c.get("id") == id), None)
    if target:
        log_action("DELETE_CONTA", f"Conta excluída: {target.get('name')} - {decimal_to_brl(target.get('amount_decimal'))}")
    
    new_list = [c for c in contas if c.get("id") != id]
    if len(new_list) == len(contas):
        flash("Conta não encontrada.", "danger")
    else:
        data["contas"] = new_list
        save_data(data)
        flash("Conta excluída.", "warning")
    return redirect(url_for("index", month=request.args.get("month") or date.today().strftime("%Y-%m")))

@app.route("/categories", methods=["GET"])
def categories_view():
    data = load_data()
    cats = data.get("categories", FIXED_CATEGORIES + [DEFAULT_EXTRA])
    cat_colors = {c.get("name"): color_for_category(c.get("name")) for c in cats}
    return render_template_string(TEMPLATE_CATEGORIES, categories=cats, cat_colors=cat_colors)

@app.route("/add_category", methods=["POST"])
def add_category():
    data = load_data()
    categories = data.setdefault("categories", FIXED_CATEGORIES + [DEFAULT_EXTRA])
    new_cat = (request.form.get("new_category") or "").strip()
    icon = (request.form.get("icon_choice") or "").strip() or "📂"
    if not new_cat:
        flash("Nome de categoria vazio.", "danger")
        return redirect(request.referrer or url_for("categories_view"))
    fixed_names = {c["name"] for c in FIXED_CATEGORIES}
    if new_cat in fixed_names:
        flash("Nome de categoria reservado (fixo). Escolha outro nome.", "warning")
        return redirect(request.referrer or url_for("categories_view"))
    if any(c.get("name").lower() == new_cat.lower() for c in categories):
        flash("Categoria já existe.", "warning")
        return redirect(request.referrer or url_for("categories_view"))
    categories.append({"name": new_cat, "icon": icon})
    save_data(data)
    log_action("CREATE_CATEGORY", f"Categoria criada: {new_cat}")
    flash(f"Categoria '{new_cat}' adicionada.", "success")
    return redirect(request.referrer or url_for("categories_view"))

@app.route("/settings", methods=["GET", "POST"])
def settings():
    data = load_data()
    if request.method == "POST":
        settings = data.setdefault("settings", {})
        settings["theme"] = request.form.get("theme") or "light"
        settings["notifications_enabled"] = request.form.get("notifications_enabled") == "on"
        try:
            settings["days_alert_before_due"] = int(request.form.get("days_alert_before_due") or 3)
            if settings["days_alert_before_due"] < 0:
                settings["days_alert_before_due"] = 0
        except Exception:
            settings["days_alert_before_due"] = 3
        
        save_data(data)
        log_action("UPDATE_SETTINGS", "Configurações atualizadas")
        flash("Configurações salvas com sucesso.", "success")
        return redirect(url_for("settings"))
    
    settings = data.get("settings", {})
    return render_template_string(TEMPLATE_SETTINGS, settings=settings)

@app.route("/export")
def export_data():
    """Exporta todos os dados em um arquivo ZIP"""
    try:
        data = load_data()
        
        # Criar arquivo ZIP em memória
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # Adicionar dados principais
            zip_file.writestr("dados.json", json.dumps(data, ensure_ascii=False, indent=2))
            
            # Adicionar histórico se existir
            if os.path.exists(HISTORY_FILE):
                with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                    history = f.read()
                zip_file.writestr("historico.json", history)
        
        zip_buffer.seek(0)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"organizador_contas_export_{timestamp}.zip"
        
        log_action("EXPORT_DATA", "Dados exportados")
        
        return send_file(
            io.BytesIO(zip_buffer.read()),
            as_attachment=True,
            download_name=filename,
            mimetype='application/zip'
        )
    except Exception as e:
        flash(f"Erro ao exportar dados: {str(e)}", "danger")
        return redirect(url_for("index"))

@app.route("/chart_data")
def chart_data():
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    data = load_data()
    contas = data.get("contas", [])
    categories = data.get("categories", FIXED_CATEGORIES + [DEFAULT_EXTRA])
    by_cat = {c.get("name"): Decimal("0") for c in categories}
    by_cat["Outros"] = by_cat.get("Outros", Decimal("0"))
    for c in contas:
        if c.get("month") == month:
            try:
                val = Decimal(str(c.get("amount_decimal","0")))
            except Exception:
                val = Decimal("0")
            cat = c.get("category") or "Outros"
            if cat not in by_cat:
                by_cat[cat] = Decimal("0")
            by_cat[cat] += val
    labels = []
    values = []
    colors = []
    for cat, val in by_cat.items():
        if val > 0:  # Só mostrar categorias com valor
            labels.append(cat)
            values.append(float(val))
            colors.append(color_for_category(cat))
    return jsonify({"labels": labels, "values": values, "colors": colors, "month": month})

# ---------- Templates Melhorados ----------
TEMPLATE_INDEX = """
<!doctype html>
<html lang="pt-br" data-theme="{{ settings.get('theme', 'light') }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>💠 Organizador de Contas</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
  <style>
    :root {
      --royal-1: #2b2f7b;
      --royal-2: #6b63b5;
      --perola: #f5f4f9;
      --accent: #bfa5ff;
      --green: #2ecc71;
      --red: #e74c3c;
      --orange: #f39c12;
      --blue: #3498db;
    }
    
    [data-theme="dark"] {
      --perola: #1a1a2e;
      --royal-1: #4a4e9b;
      --royal-2: #8b83d5;
      --accent: #cfb5ff;
    }
    
    body {
      background: linear-gradient(180deg, var(--perola), #eef0fb);
      transition: all 0.3s ease;
    }
    
    [data-theme="dark"] body {
      background: linear-gradient(180deg, var(--perola), #0f0f23);
      color: #ffffff;
    }
    
    [data-theme="dark"] .card {
      background: #16213e;
      border: 1px solid #2a3f5f;
      color: #ffffff;
    }
    
    [data-theme="dark"] .table {
      color: #ffffff;
    }
    
    [data-theme="dark"] .table th {
      color: #ffffff;
      border-color: #2a3f5f;
    }
    
    [data-theme="dark"] .table td {
      color: #ffffff;
      border-color: #2a3f5f;
    }
    
    [data-theme="dark"] .form-control,
    [data-theme="dark"] .form-select {
      background: #16213e;
      border-color: #2a3f5f;
      color: #ffffff;
    }
    
    [data-theme="dark"] .form-control:focus,
    [data-theme="dark"] .form-select:focus {
      background: #16213e;
      border-color: var(--royal-2);
      color: #ffffff;
      box-shadow: 0 0 0 0.2rem rgba(107, 99, 181, 0.25);
    }
    
    [data-theme="dark"] .modal-content {
      background: #16213e;
      color: #ffffff;
    }
    
    [data-theme="dark"] .modal-header {
      border-color: #2a3f5f;
    }
    
    [data-theme="dark"] .modal-footer {
      border-color: #2a3f5f;
    }
    
    .brand { color: var(--royal-1); font-weight: 700; }
    .card-royal {
      border-radius: 12px;
      box-shadow: 0 6px 18px rgba(100,95,150,0.08);
      transition: all 0.3s ease;
    }
    
    [data-theme="dark"] .card-royal {
      background: #16213e;
      border: 1px solid #2a3f5f;
    }
    
    .btn-royal {
      background: linear-gradient(90deg,var(--royal-2),var(--accent));
      color: white;
      border: none;
      box-shadow: 0 6px 18px rgba(107, 99, 181, 0.12);
    }
    
    .small-muted { color: #666; font-size: .9rem; }
    [data-theme="dark"] .small-muted { color: #aaa; }
    
    .status-paid { background: var(--green); color: #fff; padding: .25rem .5rem; border-radius: .35rem; }
    .status-pending { background: var(--red); color: #fff; padding: .25rem .5rem; border-radius: .35rem; }
    .status-overdue { background: #dc3545; color: #fff; padding: .25rem .5rem; border-radius: .35rem; animation: pulse 2s infinite; }
    
    .priority-urgent { border-left: 4px solid #dc3545; background: rgba(220, 53, 69, 0.1); }
    .priority-high { border-left: 4px solid var(--orange); background: rgba(243, 156, 18, 0.1); }
    .priority-normal { border-left: 4px solid var(--blue); background: rgba(52, 152, 219, 0.05); }
    .priority-low { border-left: 4px solid #6c757d; background: rgba(108, 117, 125, 0.05); }
    
    .alert-notification {
      border-left: 4px solid var(--orange);
      background: rgba(243, 156, 18, 0.1);
      margin-bottom: 1rem;
    }
    
    @keyframes pulse {
      0% { opacity: 1; }
      50% { opacity: 0.5; }
      100% { opacity: 1; }
    }
    
    .theme-toggle {
      position: fixed;
      top: 20px;
      right: 20px;
      z-index: 1000;
      background: var(--royal-2);
      border: none;
      border-radius: 50%;
      width: 50px;
      height: 50px;
      color: white;
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
  </style>
</head>
<body>
<button class="theme-toggle btn" onclick="toggleTheme()" title="Alternar tema">
  <i class="bi bi-moon-fill" id="theme-icon"></i>
</button>

<nav class="navbar navbar-expand-lg" style="background:transparent;">
  <div class="container">
    <a class="navbar-brand brand" href="{{ url_for('index') }}">💠 Organizador de Contas</a>
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary" href="{{ url_for('cadastrar') }}">
        <i class="bi bi-plus-circle"></i> Nova Conta
      </a>
      <a class="btn btn-outline-secondary" href="{{ url_for('categories_view') }}">
        <i class="bi bi-folder"></i> Categorias
      </a>
      <a class="btn btn-outline-secondary" href="{{ url_for('settings') }}">
        <i class="bi bi-gear"></i> Configurações
      </a>
      <a class="btn btn-outline-info" href="{{ url_for('export_data') }}">
        <i class="bi bi-download"></i> Exportar
      </a>
    </div>
  </div>
</nav>

<div class="container py-3">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <div class="mb-2">
      {% for cat, msg in messages %}
        <div class="alert alert-{{ 'info' if cat=='info' else cat }} alert-dismissible fade show" role="alert">
          <i class="bi bi-{{ 'info-circle' if cat=='info' else 'check-circle' if cat=='success' else 'exclamation-triangle' }}"></i>
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
      </div>
    {% endif %}
  {% endwith %}

  <!-- Alertas de Vencimento -->
  {% if alerts %}
  <div class="alert alert-notification alert-dismissible fade show" role="alert">
    <h6><i class="bi bi-bell"></i> Alertas de Vencimento</h6>
    {% for alert in alerts[:3] %}
      <div class="mb-1">
        <strong>{{ alert.conta.name }}</strong> - {{ decimal_to_brl(alert.conta.amount_decimal) }}
        {% if alert.is_overdue %}
          <span class="badge bg-danger">Vencida há {{ -alert.days_until }} dia(s)</span>
        {% elif alert.is_today %}
          <span class="badge bg-warning">Vence hoje!</span>
        {% else %}
          <span class="badge bg-info">Vence em {{ alert.days_until }} dia(s)</span>
        {% endif %}
      </div>
    {% endfor %}
    {% if alerts|length > 3 %}
      <small class="text-muted">E mais {{ alerts|length - 3 }} conta(s)...</small>
    {% endif %}
    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
  </div>
  {% endif %}

  <div class="row">
    <div class="col-lg-8">
      <div class="card card-royal p-3 mb-3">
        <div class="d-flex justify-content-between align-items-center mb-2">
          <div>
            <h5 class="mb-0">
              <i class="bi bi-calendar3"></i> Contas - mês: <strong>{{ sel_month }}</strong>
            </h5>
            <div class="small-muted">
              Total: {{ decimal_to_brl(curr_totals.total) }} • 
              Pago: <span style="color:var(--green)">{{ decimal_to_brl(curr_totals.paid) }}</span> • 
              Pendente: <span style="color:var(--red)">{{ decimal_to_brl(curr_totals.pending) }}</span>
              {% if curr_totals.overdue > 0 %}
                • <span style="color:#dc3545">Vencidas: {{ decimal_to_brl(curr_totals.overdue) }}</span>
              {% endif %}
            </div>
          </div>
          <div class="d-flex gap-2 align-items-center">
            <form method="get" class="d-flex gap-2 align-items-center">
              <button type="button" class="btn btn-sm btn-outline-secondary" onclick="changeMonth('prev')">
                <i class="bi bi-chevron-left"></i>
              </button>
              <select id="monthSelect" name="month" class="form-select form-select-sm" onchange="this.form.submit()">
                {% for m in months %}
                  <option value="{{ m }}" {% if m==sel_month %}selected{% endif %}>{{ m }}</option>
                {% endfor %}
              </select>
              <button type="button" class="btn btn-sm btn-outline-secondary" onclick="changeMonth('next')">
                <i class="bi bi-chevron-right"></i>
              </button>
            </form>
          </div>
        </div>

        <div class="d-flex gap-2 mb-3">
          <select id="filterCategory" name="category" class="form-select w-auto" onchange="onCategoryChange()">
            {% for cat in categories %}
              <option value="{{ cat }}" {% if cat==sel_category %}selected{% endif %}>{{ cat }}</option>
            {% endfor %}
          </select>
          <input id="searchBox" type="search" class="form-control" placeholder="🔍 Buscar por nome ou nota..." value="{{ q_search }}" oninput="onSearchChange()">
        </div>

        {% if contas %}
        <div class="table-responsive">
          <table id="contasTable" class="table align-middle">
            <thead>
              <tr>
                <th><i class="bi bi-card-text"></i> Nome</th>
                <th><i class="bi bi-tag"></i> Categoria</th>
                <th><i class="bi bi-currency-dollar"></i> Valor</th>
                <th><i class="bi bi-calendar-check"></i> Vencimento</th>
                <th><i class="bi bi-check-circle"></i> Status</th>
                <th class="text-end"><i class="bi bi-gear"></i> Ações</th>
              </tr>
            </thead>
            <tbody>
              {% for c in contas %}
              <tr data-name="{{ (c.get('name','') + ' ' + (c.get('notes','') or '') ).lower() | e }}" 
                  class="priority-{{ c.get('priority', 'normal') }}">
                <td>
                  <div class="d-flex align-items-center gap-2">
                    {% if c.get('priority') == 'urgent' %}
                      <i class="bi bi-exclamation-triangle text-danger"></i>
                    {% elif c.get('priority') == 'high' %}
                      <i class="bi bi-arrow-up text-warning"></i>
                    {% elif c.get('priority') == 'low' %}
                      <i class="bi bi-arrow-down text-muted"></i>
                    {% endif %}
                    <div>
                      <strong>{{ c.get('name') }}</strong>
                      {% if c.get('notes') %}
                        <div class="small-muted">{{ c.get('notes') }}</div>
                      {% endif %}
                    </div>
                  </div>
                </td>
                <td>
                  {% set catname = c.get('category') or 'Outros' %}
                  {% for cf in categories_full %}
                    {% if cf.get('name') == catname %}
                      <span style="font-size:1.1rem">{{ cf.get('icon') }}</span> {{ catname }}
                    {% endif %}
                  {% endfor %}
                  {% if catname not in (categories_full | map(attribute='name') | list) %}
                    <span>📂 {{ catname }}</span>
                  {% endif %}
                </td>
                <td><strong>{{ decimal_to_brl(c.get('amount_decimal')) }}</strong></td>
                <td>
                  {% if c.get('due_date') %}
                    {% set due_date = c.get('due_date')[:10] %}
                    {{ due_date }}
                    {% if due_date < today and c.get('status') != 'paid' %}
                      <br><small class="text-danger"><i class="bi bi-exclamation-triangle"></i> Vencida</small>
                    {% endif %}
                  {% endif %}
                </td>
                <td>
                  {% if c.get('status') == 'paid' %}
                    <span class="status-paid"><i class="bi bi-check-circle"></i> Pago</span>
                    {% if c.get('paid_at') %}
                      <div class="small-muted">em {{ c.get('paid_at')[:10] }}</div>
                    {% endif %}
                  {% else %}
                    {% set due_date = c.get('due_date', '')[:10] %}
                    {% if due_date and due_date < today %}
                      <span class="status-overdue"><i class="bi bi-exclamation-triangle"></i> Vencida</span>
                    {% else %}
                      <span class="status-pending"><i class="bi bi-clock"></i> Pendente</span>
                    {% endif %}
                  {% endif %}
                  {% if c.get('recorrente') %}
                    <div class="small-muted mt-1"><i class="bi bi-arrow-repeat"></i> Recorrente</div>
                  {% endif %}
                  {% if c.get('parcelada') %}
                    <div class="small-muted mt-1"><i class="bi bi-credit-card"></i> Parcela {{ c.get('parcel_index', '?') }}/{{ c.get('parcel_total', c.get('parcelas', '?')) }}</div>
                  {% endif %}
                </td>
                <td class="text-end">
                  <div class="btn-group" role="group">
                    <a class="btn btn-sm btn-outline-primary" href="{{ url_for('edit', id=c.get('id')) }}?month={{ sel_month }}" title="Editar">
                      <i class="bi bi-pencil"></i>
                    </a>

                    {% if c.get('status') == 'paid' %}
                      <form method="post" action="{{ url_for('toggle_pay', id=c.get('id')) }}?month={{ sel_month }}" style="display:inline">
                        <button class="btn btn-sm btn-warning" type="submit" title="Desfazer pagamento">
                          <i class="bi bi-arrow-counterclockwise"></i>
                        </button>
                      </form>
                    {% else %}
                      <button class="btn btn-sm btn-success" data-id="{{ c.get('id') }}" data-amount="{{ c.get('amount_decimal') }}" data-month="{{ c.get('month') }}" data-bs-toggle="modal" data-bs-target="#payModal" onclick="openPayModalFromBtn(this)" title="Marcar como paga">
                        <i class="bi bi-check-circle"></i>
                      </button>
                    {% endif %}

                    <form method="post" action="{{ url_for('delete', id=c.get('id')) }}?month={{ sel_month }}" style="display:inline" onsubmit="return confirm('⚠️ Tem certeza que deseja excluir esta conta?\\n\\nEsta ação não pode ser desfeita.')">
                      <button class="btn btn-sm btn-outline-danger" title="Excluir">
                        <i class="bi bi-trash"></i>
                      </button>
                    </form>
                  </div>
                </td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
        {% else %}
          <div class="p-4 text-center small-muted">
            <i class="bi bi-inbox" style="font-size: 3rem; opacity: 0.3;"></i>
            <p class="mt-2">Nenhuma conta cadastrada para este mês.</p>
            <a class="btn btn-royal" href="{{ url_for('cadastrar') }}">
              <i class="bi bi-plus-circle"></i> Cadastrar primeira conta
            </a>
          </div>
        {% endif %}
      </div>
    </div>

    <div class="col-lg-4">
      <div class="card p-3 card-royal mb-3">
        <h6><i class="bi bi-graph-up"></i> Resumo - {{ sel_month }}</h6>
        <div class="mt-2">
          <div class="d-flex gap-2">
            <div class="p-2 card-royal" style="flex:1; text-align:center">
              <small class="small-muted">Total</small>
              <div style="font-weight:700">{{ decimal_to_brl(curr_totals.total) }}</div>
            </div>
            <div class="p-2 card-royal" style="flex:1; text-align:center; background:#e8fbef;">
              <small class="small-muted">Pago</small>
              <div style="font-weight:700; color:var(--green)">{{ decimal_to_brl(curr_totals.paid) }}</div>
            </div>
            <div class="p-2 card-royal" style="flex:1; text-align:center; background:#fdecec;">
              <small class="small-muted">Pendente</small>
              <div style="font-weight:700; color:var(--red)">{{ decimal_to_brl(curr_totals.pending) }}</div>
            </div>
          </div>

          {% if curr_totals.overdue > 0 %}
          <div class="mt-2 p-2 card-royal" style="text-align:center; background:#fff5f5; border: 1px solid #fed7d7;">
            <small class="small-muted">Vencidas</small>
            <div style="font-weight:700; color:#dc3545">{{ decimal_to_brl(curr_totals.overdue) }}</div>
          </div>
          {% endif %}

          <hr>
          <p class="small-muted">Mês anterior: <strong>{{ prev_month_key or '—' }}</strong></p>
          <p class="mb-1 small-muted">Total anterior:</p>
          <p class="mb-1">{{ decimal_to_brl(prev_totals.total) }}</p>

          <div class="mt-3">
            <p class="small-muted">Variação vs mês anterior:</p>
            {% if diff > 0 %}
              <div class="text-danger">
                <i class="bi bi-arrow-up"></i> 
                <strong>+ {{ decimal_to_brl(diff) }}{% if percent %} ({{ percent }}%){% endif %}</strong>
              </div>
            {% elif diff < 0 %}
              <div class="text-success">
                <i class="bi bi-arrow-down"></i> 
                <strong>- {{ decimal_to_brl(-diff) }}{% if percent %} ({{ percent }}%){% endif %}</strong>
              </div>
            {% else %}
              <div class="small-muted">
                <i class="bi bi-dash"></i> 
                <strong>Sem alteração</strong>
              </div>
            {% endif %}
          </div>
        </div>
      </div>

      <div class="card p-3 card-royal mb-3">
        <h6><i class="bi bi-bar-chart"></i> Gastos por categoria</h6>
        <div class="d-flex gap-2 mb-2">
          <select id="chartMonth" class="form-select" onchange="refreshChart()"></select>
        </div>
        <canvas id="catChart" style="max-width:400px; height:300px; margin:0 auto; display:block"></canvas>
        <p class="mt-2 small-muted">Selecione o mês no seletor acima para atualizar o gráfico.</p>
      </div>

      <div class="card p-3 card-royal">
        <h6><i class="bi bi-lightning"></i> Ações Rápidas</h6>
        <div class="mt-2 d-grid gap-2">
          <a class="btn btn-royal" href="{{ url_for('cadastrar') }}">
            <i class="bi bi-plus-circle"></i> Nova Conta
          </a>
          <a class="btn btn-outline-secondary" href="{{ url_for('categories_view') }}">
            <i class="bi bi-folder"></i> Gerenciar categorias
          </a>
          <a class="btn btn-outline-info" href="{{ url_for('export_data') }}">
            <i class="bi bi-download"></i> Exportar dados
          </a>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Pay Modal -->
<div class="modal fade" id="payModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <form id="payForm" method="post" class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title"><i class="bi bi-check-circle"></i> Marcar pagamento</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Fechar"></button>
      </div>
      <div class="modal-body">
        <div class="mb-3">
          <label class="form-label">Valor pago</label>
          <input name="paid_amount" id="modalPaidAmount" class="form-control" placeholder="Ex: 150.50">
          <div class="form-text small-muted">Deixe vazio para usar o valor original.</div>
        </div>
        <div class="mb-3">
          <label class="form-label">Data do pagamento</label>
          <input name="paid_date" id="modalPaidDate" type="date" class="form-control">
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-royal" type="submit">
          <i class="bi bi-check-circle"></i> Confirmar Pagamento
        </button>
        <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancelar</button>
      </div>
    </form>
  </div>
</div>

<footer class="container text-center mt-3">
  <p class="small-muted">
    <i class="bi bi-shield-check"></i> Aplicação local • 
    <i class="bi bi-hdd"></i> Salva em <code>dados.json</code> • 
    <i class="bi bi-clock-history"></i> Histórico de ações
  </p>
</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
  // Theme management
  function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-theme') || 'light';
    const newTheme = currentTheme === 'light' ? 'dark' : 'light';
    html.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme', newTheme);
    updateThemeIcon(newTheme);
  }
  
  function updateThemeIcon(theme) {
    const icon = document.getElementById('theme-icon');
    icon.className = theme === 'light' ? 'bi bi-moon-fill' : 'bi bi-sun-fill';
  }
  
  // Load saved theme
  document.addEventListener('DOMContentLoaded', function() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    updateThemeIcon(savedTheme);
  });

  // Chart months population
  (function populateChartMonths(){
    const sel = document.getElementById('chartMonth');
    const urlMonth = new URLSearchParams(window.location.search).get('month');
    const months = [];
    const today = new Date();
    for (let i=11; i>=0; i--){
      const d = new Date(today.getFullYear(), today.getMonth() - i, 1);
      const m = d.getFullYear().toString().padStart(4,'0') + '-' + ( (d.getMonth()+1).toString().padStart(2,'0') );
      months.push(m);
    }
    months.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      opt.text = m;
      sel.appendChild(opt);
    });
    const defaultMonth = urlMonth || (new Date().getFullYear() + '-' + String(new Date().getMonth()+1).padStart(2,'0'));
    sel.value = defaultMonth;
  })();

  let catChart = null;
  async async function refreshChart(){
  const month = document.getElementById('chartMonth').value;
  const res = await fetch(`/chart_data?month=${encodeURIComponent(month)}`);
  const json = await res.json();
  const labels = json.labels;
  const values = json.values;
  const colors = json.colors;
  const ctx = document.getElementById('catChart').getContext('2d');

  if(catChart) catChart.destroy();

  catChart = new Chart(ctx, {
    type: 'pie',
    data: {
      labels: labels,
      datasets: [{
        data: values,
        backgroundColor: colors
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom'
        }
      }
    }
  });
}`);
    const json = await res.json();
    const labels = json.labels;
    const values = json.values;
    const colors = json.colors;
    const ctx = document.getElementById('catChart').getContext('2d');
    if(catChart) catChart.destroy();
    catChart = new Chart(ctx, {
      type: 'pie',
      data: {
        labels: labels,
        datasets: [{
          data: Object.values(data),
          backgroundColor: [
            '#6b63b5', '#2ecc71', '#e74c3c', '#f39c12', '#3498db', '#9b59b6'
          ]
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: {
            display: false
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              callback: function(value) {
                return 'R$ ' + value.toLocaleString('pt-BR', {minimumFractionDigits: 2});
              }
            }
          },
          x: {
            ticks: {
              maxRotation: 45,
              minRotation: 0
            }
          }
        }
      }
    });
  }

  document.addEventListener('DOMContentLoaded', function(){
    refreshChart();
    const q = document.getElementById('searchBox').value;
    if(q) onSearchChange();
  });

  function onSearchChange(){
    const q = document.getElementById('searchBox').value.toLowerCase();
    const month = "{{ sel_month }}";
    const cat = document.getElementById('filterCategory').value;
    const params = new URLSearchParams();
    if(month) params.set('month', month);
    if(cat) params.set('category', cat);
    if(q) params.set('q', q);
    window.history.replaceState({}, '', `${location.pathname}?${params.toString()}`);
    const rows = document.querySelectorAll('#contasTable tbody tr');
    rows.forEach(r => {
      const name = r.getAttribute('data-name') || '';
      if(name.includes(q)) r.style.display = '';
      else r.style.display = 'none';
    });
  }
  
  function onCategoryChange(){
    const q = document.getElementById('searchBox').value;
    const month = "{{ sel_month }}";
    const cat = document.getElementById('filterCategory').value;
    const params = new URLSearchParams();
    if(month) params.set('month', month);
    if(cat) params.set('category', cat);
    if(q) params.set('q', q);
    window.location = `${location.pathname}?${params.toString()}`;
  }

  let currentPayId = null;
  function openPayModalFromBtn(btn){
    currentPayId = btn.dataset.id;
    document.getElementById('modalPaidAmount').value = '';
    document.getElementById('modalPaidDate').value = new Date().toISOString().split('T')[0];
    const form = document.getElementById('payForm');
    form.action = `/toggle_pay/${currentPayId}?month=${encodeURIComponent("{{ sel_month }}")}`;
  }

  function changeMonth(dir){
    const select = document.getElementById('monthSelect');
    let idx = select.selectedIndex;
    if(dir === 'prev') idx = Math.min(select.options.length - 1, idx + 1);
    if(dir === 'next') idx = Math.max(0, idx - 1);
    select.selectedIndex = idx;
    select.form.submit();
  }
</script>
</body>
</html>
"""

TEMPLATE_CADASTRAR = """
<!doctype html>
<html lang="pt-br" data-theme="{{ settings.get('theme', 'light') if settings else 'light' }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% if form.id %}✏️ Editar Conta{% else %}➕ Nova Conta{% endif %}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
  <style>
    :root{ --royal-1:#2b2f7b; --royal-2:#6b63b5; --perola:#f5f4f9; --accent:#bfa5ff; }
    
    [data-theme="dark"] {
      --perola: #1a1a2e;
      --royal-1: #4a4e9b;
      --royal-2: #8b83d5;
      --accent: #cfb5ff;
    }
    
    body{ 
      background: linear-gradient(180deg, var(--perola), #eef0fb); 
      transition: all 0.3s ease;
    }
    
    [data-theme="dark"] body {
      background: linear-gradient(180deg, var(--perola), #0f0f23);
      color: #ffffff;
    }
    
    [data-theme="dark"] .card {
      background: #16213e;
      border: 1px solid #2a3f5f;
      color: #ffffff;
    }
    
    [data-theme="dark"] .form-control,
    [data-theme="dark"] .form-select,
    [data-theme="dark"] textarea {
      background: #16213e;
      border-color: #2a3f5f;
      color: #ffffff;
    }
    
    [data-theme="dark"] .form-control:focus,
    [data-theme="dark"] .form-select:focus,
    [data-theme="dark"] textarea:focus {
      background: #16213e;
      border-color: var(--royal-2);
      color: #ffffff;
      box-shadow: 0 0 0 0.2rem rgba(107, 99, 181, 0.25);
    }
    
    [data-theme="dark"] .input-group-text {
      background: #16213e;
      border-color: #2a3f5f;
      color: #ffffff;
    }
    
    .brand { color: var(--royal-1); font-weight:700; }
    .card-royal { 
      border-radius: 12px; 
      box-shadow: 0 6px 18px rgba(100,95,150,0.08); 
      transition: all 0.3s ease;
    }
    
    [data-theme="dark"] .card-royal {
      background: #16213e;
      border: 1px solid #2a3f5f;
    }
    
    .btn-royal { background: linear-gradient(90deg,var(--royal-2),var(--accent)); color: white; border: none; box-shadow: 0 6px 18px rgba(107, 99, 181, 0.12); }
    .small-muted { color:#666; font-size:.9rem; }
    [data-theme="dark"] .small-muted { color: #aaa; }
    
    .form-control:focus, .form-select:focus {
      border-color: var(--royal-2);
      box-shadow: 0 0 0 0.2rem rgba(107, 99, 181, 0.25);
    }
    
    .priority-indicator {
      width: 20px;
      height: 20px;
      border-radius: 50%;
      display: inline-block;
      margin-right: 8px;
    }
    
    .priority-urgent { background: #dc3545; }
    .priority-high { background: #f39c12; }
    .priority-normal { background: #3498db; }
    .priority-low { background: #6c757d; }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg" style="background:transparent;">
  <div class="container">
    <a class="navbar-brand brand" href="{{ url_for('index') }}">💠 Organizador de Contas</a>
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary" href="{{ url_for('index') }}">
        <i class="bi bi-arrow-left"></i> Voltar
      </a>
    </div>
  </div>
</nav>

<div class="container py-4">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <div class="mb-2">
      {% for cat, msg in messages %}
        <div class="alert alert-{{ 'info' if cat=='info' else cat }} alert-dismissible fade show" role="alert">
          <i class="bi bi-{{ 'info-circle' if cat=='info' else 'check-circle' if cat=='success' else 'exclamation-triangle' }}"></i>
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
      </div>
    {% endif %}
  {% endwith %}

  <div class="row justify-content-center">
    <div class="col-lg-8">
      <div class="card card-royal p-4">
        <h5>
          {% if form.id %}
            <i class="bi bi-pencil"></i> Editar Conta
          {% else %}
            <i class="bi bi-plus-circle"></i> Nova Conta
          {% endif %}
        </h5>
        
        <form method="post" class="mt-4" id="contaForm">
          <div class="row">
            <div class="col-md-8">
              <div class="mb-3">
                <label class="form-label">
                  <i class="bi bi-card-text"></i> Nome da conta *
                </label>
                <input name="name" class="form-control" required placeholder="ex: Luz, Água, Internet" autofocus value="{{ form.name }}" maxlength="100">
              </div>
            </div>
            <div class="col-md-4">
              <div class="mb-3">
                <label class="form-label">
                  <i class="bi bi-flag"></i> Prioridade
                </label>
                <select name="priority" class="form-select" onchange="updatePriorityIndicator()">
                  <option value="low" {% if form.priority == 'low' %}selected{% endif %}>
                    🔵 Baixa
                  </option>
                  <option value="normal" {% if form.priority == 'normal' or not form.priority %}selected{% endif %}>
                    🔷 Normal
                  </option>
                  <option value="high" {% if form.priority == 'high' %}selected{% endif %}>
                    🟠 Alta
                  </option>
                  <option value="urgent" {% if form.priority == 'urgent' %}selected{% endif %}>
                    🔴 Urgente
                  </option>
                </select>
              </div>
            </div>
          </div>

          <div class="row">
            <div class="col-md-6">
              <div class="mb-3">
                <label class="form-label">
                  <i class="bi bi-tag"></i> Categoria *
                </label>
                <select name="category" class="form-select" required>
                  {% for cat in categories %}
                    <option value="{{ cat.get('name') }}" {% if cat.get('name') == form.category %}selected{% endif %}>
                      {{ cat.get('icon') }} {{ cat.get('name') }}
                    </option>
                  {% endfor %}
                </select>
              </div>
            </div>
            <div class="col-md-6">
              <div class="mb-3">
                <label class="form-label">
                  <i class="bi bi-currency-dollar"></i> Valor *
                </label>
                <div class="input-group">
                  <span class="input-group-text">R$</span>
                  <input name="value" class="form-control" required placeholder="150.50" inputmode="decimal" value="{{ form.value }}" pattern="[0-9]+([,.][0-9]{1,2})?" title="Digite um valor válido (ex: 150.50)">
                </div>
                <div class="form-text small-muted">Digite números (ex: 150.50 ou 150,50)</div>
              </div>
            </div>
          </div>

          <div class="row">
            <div class="col-md-6">
              <div class="mb-3">
                <label class="form-label">
                  <i class="bi bi-calendar3"></i> Mês de referência *
                </label>
                <input name="mes" type="month" class="form-control" value="{{ form.mes }}" required>
                <div class="form-text small-muted">A conta será atribuída ao mês selecionado</div>
              </div>
            </div>
            <div class="col-md-6">
              <div class="mb-3">
                <label class="form-label">
                  <i class="bi bi-calendar-check"></i> Data de vencimento
                </label>
                <input name="due_date" type="date" class="form-control" value="{{ form.due_date }}">
                <div class="form-text small-muted">Deixe vazio para usar o dia 15 do mês</div>
              </div>
            </div>
          </div>

          <div class="mb-3">
            <label class="form-label">
              <i class="bi bi-chat-text"></i> Observações
            </label>
            <textarea name="notes" class="form-control" rows="2" placeholder="Informações adicionais sobre esta conta..." maxlength="500">{{ form.notes }}</textarea>
          </div>

          <hr class="my-4">
          
          <h6><i class="bi bi-gear"></i> Configurações Avançadas</h6>
          
          <div class="row">
            <div class="col-md-6">
              <div class="mb-3 form-check">
                <input type="checkbox" class="form-check-input" id="recorrente_indef" name="recorrente_indef" {% if form.recorrente_indef %}checked{% endif %}>
                <label class="form-check-label" for="recorrente_indef">
                  <i class="bi bi-arrow-repeat"></i> Recorrente (indefinida)
                </label>
                <div class="form-text small-muted">Gera a próxima fatura automaticamente com valor = 0</div>
              </div>

              <div class="mb-3">
                <label class="form-label">
                  <i class="bi bi-calendar-range"></i> Recorrência por X meses
                </label>
                <input name="recorrencia_months" type="number" min="0" max="60" class="form-control" placeholder="Ex: 6 (deixe 0 para não usar)" value="{{ form.recorrencia_months }}">
                <div class="form-text small-muted">Se >0, gera cópias pelos próximos X meses mantendo o valor do mês anterior</div>
              </div>
            </div>
            
            <div class="col-md-6">
              <div class="mb-3 form-check">
                <input type="checkbox" class="form-check-input" id="parcelada" name="parcelada" onchange="toggleParcelas(this)" {% if form.parcelada %}checked{% endif %}>
                <label class="form-check-label" for="parcelada">
                  <i class="bi bi-credit-card"></i> Parcelada
                </label>
              </div>

              <div class="mb-3" id="parcelasBox" style="display: {% if form.parcelada %}block{% else %}none{% endif %};">
                <label class="form-label">
                  <i class="bi bi-list-ol"></i> Número de parcelas
                </label>
                <input name="parcelas" type="number" min="1" max="60" class="form-control" value="{{ form.parcelas or 1 }}">
                <div class="form-text small-muted">Se >1, o valor será dividido e as próximas parcelas serão geradas automaticamente</div>
              </div>
            </div>
          </div>

          <div class="d-flex gap-2 mt-4">
            <button class="btn btn-royal" type="submit">
              {% if form.id %}
                <i class="bi bi-check-circle"></i> Atualizar Conta
              {% else %}
                <i class="bi bi-plus-circle"></i> Salvar Conta
              {% endif %}
            </button>
            <a class="btn btn-outline-secondary" href="{{ url_for('index') }}">
              <i class="bi bi-x-circle"></i> Cancelar
            </a>
          </div>
        </form>
      </div>

      <div class="card card-royal p-3 mt-3">
        <h6><i class="bi bi-lightning"></i> Adicionar categoria rápida</h6>
        <form method="post" action="{{ url_for('add_category') }}" class="d-flex gap-2">
          <input name="new_category" class="form-control" placeholder="Nova categoria" maxlength="50">
          <select name="icon_choice" class="form-select" style="max-width:110px">
            <option value="📂">📂</option><option value="💡">💡</option><option value="💧">💧</option>
            <option value="🌐">🌐</option><option value="🛒">🛒</option><option value="💳">💳</option>
            <option value="👸">👸</option><option value="🍔">🍔</option><option value="🚗">🚗</option>
            <option value="🎵">🎵</option><option value="🏠">🏠</option><option value="⚡">⚡</option>
          </select>
          <button class="btn btn-royal" type="submit">
            <i class="bi bi-plus"></i> Adicionar
          </button>
        </form>
      </div>
    </div>
  </div>
</div>

<footer class="container text-center mt-4">
  <p class="small-muted">
    <i class="bi bi-shield-check"></i> Aplicação local • 
    <i class="bi bi-hdd"></i> Salva em <code>dados.json</code>
  </p>
</footer>

<script>
  function toggleParcelas(cb){
    document.getElementById('parcelasBox').style.display = cb.checked ? 'block' : 'none';
  }
  
  function updatePriorityIndicator() {
    // Função para futura implementação de indicador visual
  }
  
  // Validação de formulário
  document.getElementById('contaForm').addEventListener('submit', function(e) {
    const name = document.querySelector('input[name="name"]').value.trim();
    const value = document.querySelector('input[name="value"]').value.trim();
    
    if (!name) {
      e.preventDefault();
      alert('⚠️ Nome da conta é obrigatório!');
      return false;
    }
    
    if (!value) {
      e.preventDefault();
      alert('⚠️ Valor é obrigatório!');
      return false;
    }
    
    // Validar formato do valor (corrigido)
    const valueRegex = /^\\d+([,.]\\d{1,2})?$/;
    if (!valueRegex.test(value)) {
      e.preventDefault();
      alert('⚠️ Formato de valor inválido! Use: 150.50 ou 150,50');
      return false;
    }
  });
  
  // Load theme
  document.addEventListener('DOMContentLoaded', function() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
  });
</script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

TEMPLATE_CATEGORIES = """
<!doctype html>
<html lang="pt-br" data-theme="light">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>📂 Categorias</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
  <style>
    :root{ --royal-1:#2b2f7b; --royal-2:#6b63b5; --perola:#f5f4f9; --accent:#bfa5ff; }
    
    [data-theme="dark"] {
      --perola: #1a1a2e;
      --royal-1: #4a4e9b;
      --royal-2: #8b83d5;
      --accent: #cfb5ff;
    }
    
    body{ 
      background: linear-gradient(180deg, var(--perola), #eef0fb); 
      transition: all 0.3s ease;
    }
    
    [data-theme="dark"] body {
      background: linear-gradient(180deg, var(--perola), #0f0f23);
      color: #ffffff;
    }
    
    [data-theme="dark"] .card {
      background: #16213e;
      border: 1px solid #2a3f5f;
      color: #ffffff;
    }
    
    [data-theme="dark"] .modal-content {
      background: #16213e;
      color: #ffffff;
    }
    
    [data-theme="dark"] .form-control,
    [data-theme="dark"] .form-select {
      background: #16213e;
      border-color: #2a3f5f;
      color: #ffffff;
    }
    
    .brand { color: var(--royal-1); font-weight:700; }
    .card-royal { border-radius: 12px; box-shadow: 0 6px 18px rgba(100,95,150,0.08); }
    
    [data-theme="dark"] .card-royal {
      background: #16213e;
      border: 1px solid #2a3f5f;
    }
    
    .btn-royal { background: linear-gradient(90deg,var(--royal-2),var(--accent)); color: white; border: none; }
    .category-badge {
      padding: .8rem 1.2rem;
      margin: .5rem;
      border-radius: .5rem;
      display: inline-block;
      transition: all 0.3s ease;
      border: 2px solid transparent;
    }
    .category-badge:hover {
      transform: translateY(-2px);
      box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg" style="background:transparent;">
  <div class="container">
    <a class="navbar-brand brand" href="{{ url_for('index') }}">💠 Organizador de Contas</a>
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary" href="{{ url_for('cadastrar') }}">
        <i class="bi bi-plus-circle"></i> Nova Conta
      </a>
      <button class="btn btn-royal" data-bs-toggle="modal" data-bs-target="#addCategoryModal">
        <i class="bi bi-plus"></i> Adicionar categoria
      </button>
      <a class="btn btn-outline-secondary" href="{{ url_for('index') }}">
        <i class="bi bi-arrow-left"></i> Voltar
      </a>
    </div>
  </div>
</nav>

<div class="container py-4">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <div class="mb-2">
      {% for cat, msg in messages %}
        <div class="alert alert-{{ 'info' if cat=='info' else cat }} alert-dismissible fade show" role="alert">
          <i class="bi bi-{{ 'info-circle' if cat=='info' else 'check-circle' if cat=='success' else 'exclamation-triangle' }}"></i>
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
      </div>
    {% endif %}
  {% endwith %}

  <div class="row justify-content-center">
    <div class="col-lg-10">
      <div class="card card-royal p-4 mb-3">
        <div class="d-flex justify-content-between align-items-center mb-3">
          <h5><i class="bi bi-folder"></i> Categorias Disponíveis</h5>
          <span class="badge bg-info">{{ categories|length }} categoria(s)</span>
        </div>
        
        <div class="mt-3">
          <div class="d-flex flex-wrap justify-content-center">
            {% for cat in categories %}
              <div class="category-badge" style="background:{{ cat_colors.get(cat.get('name')) }}; color:#fff;">
                <div style="font-size: 1.5rem; margin-bottom: 0.5rem;">{{ cat.get('icon') }}</div>
                <div style="font-weight: 600;">{{ cat.get('name') }}</div>
              </div>
            {% endfor %}
          </div>
        </div>
        
        <div class="mt-4 p-3" style="background: rgba(107, 99, 181, 0.1); border-radius: 8px;">
          <h6><i class="bi bi-info-circle"></i> Informações</h6>
          <ul class="mb-0 small">
            <li>As categorias fixas (Luz, Água, Internet, etc.) não podem ser removidas</li>
            <li>Você pode adicionar quantas categorias personalizadas precisar</li>
            <li>Cada categoria tem uma cor única gerada automaticamente</li>
            <li>As categorias são usadas para organizar e filtrar suas contas</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- add category modal -->
<div class="modal fade" id="addCategoryModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <form method="post" action="{{ url_for('add_category') }}" class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title"><i class="bi bi-plus-circle"></i> Adicionar categoria</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Fechar"></button>
      </div>
      <div class="modal-body">
        <div class="mb-3">
          <label class="form-label">Nome da categoria</label>
          <input name="new_category" class="form-control" placeholder="Ex: Streaming" required maxlength="50">
        </div>
        <div class="mb-3">
          <label class="form-label">Ícone (escolha)</label>
          <select name="icon_choice" class="form-select">
            <option value="📂">📂 Padrão</option>
            <option value="💡">💡 Luz</option>
            <option value="💧">💧 Água</option>
            <option value="🌐">🌐 Internet</option>
            <option value="🛒">🛒 Mercado</option>
            <option value="💳">💳 Cartão</option>
            <option value="👸">👸 Manuela</option>
            <option value="🍔">🍔 Alimentação</option>
            <option value="🚗">🚗 Transporte</option>
            <option value="🎵">🎵 Streaming</option>
            <option value="🧰">🧰 Serviços</option>
            <option value="🧾">🧾 Outros</option>
            <option value="🏠">🏠 Casa</option>
            <option value="⚡">⚡ Energia</option>
            <option value="📱">📱 Telefone</option>
            <option value="🎓">🎓 Educação</option>
            <option value="💊">💊 Saúde</option>
            <option value="🎮">🎮 Entretenimento</option>
          </select>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-royal" type="submit">
          <i class="bi bi-plus-circle"></i> Adicionar
        </button>
        <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancelar</button>
      </div>
    </form>
  </div>
</div>

<footer class="container text-center mt-4">
  <p class="small-muted">
    <i class="bi bi-shield-check"></i> Aplicação local • 
    <i class="bi bi-hdd"></i> Salva em <code>dados.json</code>
  </p>
</footer>

<script>
  // Load theme
  document.addEventListener('DOMContentLoaded', function() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
  });
</script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

TEMPLATE_SETTINGS = """
<!doctype html>
<html lang="pt-br" data-theme="{{ settings.get('theme', 'light') }}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>⚙️ Configurações</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css" rel="stylesheet">
  <style>
    :root{ --royal-1:#2b2f7b; --royal-2:#6b63b5; --perola:#f5f4f9; --accent:#bfa5ff; }
    
    [data-theme="dark"] {
      --perola: #1a1a2e;
      --royal-1: #4a4e9b;
      --royal-2: #8b83d5;
      --accent: #cfb5ff;
    }
    
    body{ 
      background: linear-gradient(180deg, var(--perola), #eef0fb); 
      transition: all 0.3s ease;
    }
    
    [data-theme="dark"] body {
      background: linear-gradient(180deg, var(--perola), #0f0f23);
      color: #ffffff;
    }
    
    [data-theme="dark"] .card {
      background: #16213e;
      border: 1px solid #2a3f5f;
      color: #ffffff;
    }
    
    [data-theme="dark"] .form-control,
    [data-theme="dark"] .form-select {
      background: #16213e;
      border-color: #2a3f5f;
      color: #ffffff;
    }
    
    [data-theme="dark"] .form-control:focus,
    [data-theme="dark"] .form-select:focus {
      background: #16213e;
      border-color: var(--royal-2);
      color: #ffffff;
      box-shadow: 0 0 0 0.2rem rgba(107, 99, 181, 0.25);
    }
    
    .brand { color: var(--royal-1); font-weight:700; }
    .card-royal { 
      border-radius: 12px; 
      box-shadow: 0 6px 18px rgba(100,95,150,0.08); 
      transition: all 0.3s ease;
    }
    
    [data-theme="dark"] .card-royal {
      background: #16213e;
      border: 1px solid #2a3f5f;
    }
    
    .btn-royal { background: linear-gradient(90deg,var(--royal-2),var(--accent)); color: white; border: none; }
    .small-muted { color:#666; font-size:.9rem; }
    [data-theme="dark"] .small-muted { color: #aaa; }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg" style="background:transparent;">
  <div class="container">
    <a class="navbar-brand brand" href="{{ url_for('index') }}">💠 Organizador de Contas</a>
    <div class="d-flex gap-2">
      <a class="btn btn-outline-secondary" href="{{ url_for('index') }}">
        <i class="bi bi-arrow-left"></i> Voltar
      </a>
    </div>
  </div>
</nav>

<div class="container py-4">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <div class="mb-2">
      {% for cat, msg in messages %}
        <div class="alert alert-{{ 'info' if cat=='info' else cat }} alert-dismissible fade show" role="alert">
          <i class="bi bi-{{ 'info-circle' if cat=='info' else 'check-circle' if cat=='success' else 'exclamation-triangle' }}"></i>
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
      </div>
    {% endif %}
  {% endwith %}

  <div class="row justify-content-center">
    <div class="col-lg-8">
      <div class="card card-royal p-4">
        <h5><i class="bi bi-gear"></i> Configurações do Sistema</h5>
        
        <form method="post" class="mt-4">
          <div class="row">
            <div class="col-md-6">
              <div class="mb-4">
                <h6><i class="bi bi-palette"></i> Aparência</h6>
                <div class="mb-3">
                  <label class="form-label">Tema</label>
                  <select name="theme" class="form-select" onchange="previewTheme(this.value)">
                    <option value="light" {% if settings.get('theme') == 'light' %}selected{% endif %}>
                      ☀ Claro
                    </option>
                    <option value="dark" {% if settings.get('theme') == 'dark' %}selected{% endif %}>
                      🌙 Escuro
                    </option>
                  </select>
                </div>
              </div>
            </div>
            
            <div class="col-md-6">
              <div class="mb-4">
                <h6><i class="bi bi-bell"></i> Notificações</h6>
                <div class="mb-3 form-check">
                  <input type="checkbox" class="form-check-input" id="notifications_enabled" name="notifications_enabled" {% if settings.get('notifications_enabled', True) %}checked{% endif %}>
                  <label class="form-check-label" for="notifications_enabled">
                    Alertas de vencimento
                  </label>
                </div>
                <div class="mb-3">
                  <label class="form-label">Alertar X dias antes do vencimento</label>
                  <input name="days_alert_before_due" type="number" min="0" max="30" class="form-control" value="{{ settings.get('days_alert_before_due', 3) }}">
                </div>
              </div>
            </div>
          </div>

          <hr>
          
          <div class="d-flex gap-2">
            <button class="btn btn-royal" type="submit">
              <i class="bi bi-check-circle"></i> Salvar Configurações
            </button>
            <a class="btn btn-outline-secondary" href="{{ url_for('index') }}">
              <i class="bi bi-x-circle"></i> Cancelar
            </a>
          </div>
        </form>
      </div>

      <div class="card card-royal p-4 mt-3">
        <h6><i class="bi bi-info-circle"></i> Informações do Sistema</h6>
        <div class="row mt-3">
          <div class="col-md-6">
            <p><strong>Arquivo de dados:</strong> <code>dados.json</code></p>
            <p><strong>Histórico:</strong> <code>historico.json</code></p>
          </div>
          <div class="col-md-6">
            <p><strong>Versão:</strong> 2.0 (Melhorada)</p>
            <p><strong>Gráfico:</strong> Colunas por categoria</p>
          </div>
        </div>
        
        <div class="mt-3 p-3" style="background: rgba(107, 99, 181, 0.1); border-radius: 8px;">
          <h6>🛡️ Recursos de Segurança</h6>
          <ul class="mb-0 small">
            <li>Histórico de ações registrado</li>
            <li>Validações robustas de entrada</li>
            <li>Confirmações para ações críticas</li>
            <li>Dados salvos localmente</li>
          </ul>
        </div>
      </div>
    </div>
  </div>
</div>

<footer class="container text-center mt-4">
  <p class="small-muted">
    <i class="bi bi-shield-check"></i> Aplicação local • 
    <i class="bi bi-hdd"></i> Salva em <code>dados.json</code>
  </p>
</footer>

<script>
  function previewTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
  }
  
  // Load current theme
  document.addEventListener('DOMContentLoaded', function() {
    const currentTheme = "{{ settings.get('theme', 'light') }}";
    document.documentElement.setAttribute('data-theme', currentTheme);
  });
</script>
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

# inject helpers for Jinja
@app.context_processor
def inject_helpers():
    return dict(decimal_to_brl=decimal_to_brl)

# ---------- Run server ----------
if __name__ == "__main__":
    app.run(debug=True, use_reloader=True)