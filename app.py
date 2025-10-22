# app.py
"""
Organizador de Contas - único arquivo
Revisado para:
 - edição com campos pré-preenchidos
 - desfazer pagamento (volta para pendente)
 - usa dados.json como arquivo principal (não zera)
 - recorrências automáticas
 - categorias fixas com emojis e tema moderno
 - Classes para melhor organização e escalabilidade
 - Tipagem e validação aprimoradas
 - CORREÇÃO: Problema de multiplicação por 100 nos valores corrigido
 - TEMA MODERNO: Interface repaginada com design contemporâneo
 - PRIMEIRA EXECUÇÃO: Removida opção de salvamento inicial
Compatível com Python 3.9+ e Flask
"""
from flask import Flask, request, redirect, url_for, flash, render_template_string, jsonify
import json
import os
import uuid
import calendar
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from datetime import datetime, date
import threading
import hashlib
from typing import List, Dict, Any, Optional, Tuple

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "troque_essa_chave_para_uma_aleatoria_e_complexa_em_producao")

# ---------- Constantes e Configurações ----------
DATA_FILE = "dados.json"
# REMOVIDO: FIRST_RUN_FLAG - não há mais primeira execução especial
DATA_LOCK = threading.Lock()

FIXED_CATEGORIES_DATA: List[Dict[str, str]] = [
    {"name": "Luz", "icon": "💡"},
    {"name": "Água", "icon": "💧"},
    {"name": "Internet", "icon": "🌐"},
    {"name": "Mercado", "icon": "🛒"},
    {"name": "Cartão", "icon": "💳"},
    {"name": "Manuela", "icon": "👸"},
]
DEFAULT_EXTRA_CATEGORY_DATA: Dict[str, str] = {"name": "Outros", "icon": "🧾"}

# ---------- Utilitários ----------
def money_to_decimal(value_str: Optional[str]) -> Decimal:
    """Converte uma string monetária (BR/US) para Decimal."""
    if value_str is None:
        raise InvalidOperation("Valor monetário não pode ser nulo.")
    v = str(value_str).strip().replace(" ", "")
    # CORREÇÃO: Melhor tratamento de formato monetário
    # Remove R$ se presente
    v = v.replace("R$", "").strip()
    # Se tem ponto E vírgula, assume formato brasileiro (1.234,56)
    if "." in v and "," in v:
        v = v.replace(".", "").replace(",", ".")
    # Se tem apenas vírgula, assume formato brasileiro (1234,56)
    elif "," in v and "." not in v:
        v = v.replace(",", ".")
    # Se tem apenas ponto, pode ser formato americano (1234.56) ou separador de milhares (1.234)
    # Assumimos formato americano se há apenas um ponto
    return Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def decimal_to_brl(d: Optional[Decimal]) -> str:
    """Converte Decimal para string formatada em BRL."""
    try:
        if d is None:
            raise InvalidOperation
        d = Decimal(d)
        q = f"{d:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except InvalidOperation:
        q = "0,00"
    return "R$ " + q

def month_key_from_date(dt: date) -> str:
    """Retorna a chave do mês (YYYY-MM) de um objeto date."""
    return dt.strftime("%Y-%m")

def parse_month_input(s: Optional[str]) -> Optional[date]:
    """Converte string YYYY-MM para objeto date (primeiro dia do mês)."""
    if not s:
        return None
    try:
        parts = s.split("-")
        y = int(parts[0])
        m = int(parts[1])
        return date(y, m, 1)
    except (ValueError, IndexError):
        return None

def add_months(sourcedate: date, months: int) -> date:
    """Adiciona/subtrai meses de uma data, ajustando o dia se necessário."""
    month = sourcedate.month - 1 + months
    year = sourcedate.year + month // 12
    month = month % 12 + 1
    day = min(sourcedate.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)

def split_amount_into_installments(amount: Decimal, n: int) -> List[Decimal]:
    """Divide um valor em N parcelas, ajustando o último para totalizar o valor."""
    if n <= 1:
        return [amount.quantize(Decimal("0.01"))]
    amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    base = (amount / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    parts = [base for _ in range(n)]
    total_parts = sum(parts)
    diff = amount - total_parts
    if diff != Decimal("0"):
        parts[-1] = (parts[-1] + diff).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return parts

def color_for_category(name: str) -> str:
    """Gera uma cor HSL determinística (e depois HEX) para um nome de categoria."""
    h = int(hashlib.sha1(name.encode("utf-8")).hexdigest()[:8], 16)
    hue = h % 360
    sat = 70  # Aumentado para cores mais vibrantes
    light = 50  # Ajustado para melhor contraste
    return hsl_to_hex(hue, sat, light)

def hsl_to_hex(h: int, s: int, l: int) -> str:
    """Converte HSL para HEX."""
    s /= 100.0
    l /= 100.0
    c = (1 - abs(2 * l - 1)) * s
    x = c * (1 - abs((h / 60.0) % 2 - 1))
    m = l - c/2
    if h < 60: r1, g1, b1 = c, x, 0
    elif h < 120: r1, g1, b1 = x, c, 0
    elif h < 180: r1, g1, b1 = 0, c, x
    elif h < 240: r1, g1, b1 = 0, x, c
    elif h < 300: r1, g1, b1 = x, 0, c
    else: r1, g1, b1 = c, 0, x
    r = int((r1 + m) * 255)
    g = int((g1 + m) * 255)
    b = int((b1 + m) * 255)
    return '#{:02x}{:02x}{:02x}'.format(r, g, b)

# REMOVIDO: Funções is_first_run() e mark_first_run_complete()

# ---------- Classes de Entidade ----------
class Category:
    """Representa uma categoria de conta."""
    def __init__(self, name: str, icon: str = "📂"):
        if not name:
            raise ValueError("O nome da categoria não pode ser vazio.")
        self.name: str = name
        self.icon: str = icon

    def to_dict(self) -> Dict[str, str]:
        return {"name": self.name, "icon": self.icon}

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Category':
        return Category(name=data["name"], icon=data.get("icon", "📂"))

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Category):
            return NotImplemented
        return self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)

class Conta:
    """Representa uma conta a pagar/paga."""
    def __init__(self,
                 name: str,
                 amount_decimal: Decimal,
                 month: str, # YYYY-MM
                 category: str = "Outros",
                 notes: str = "",
                 status: str = "pending", # "pending" ou "paid"
                 paid_at: Optional[datetime] = None,
                 paid_amount: Optional[Decimal] = None,
                 created_at: Optional[datetime] = None,
                 recorrente: bool = False,
                 rec_type: Optional[str] = None, # "indef" ou "fixed"
                 recorrencia_months: int = 0,
                 rec_origin: Optional[str] = None, # ID da conta original se for uma recorrência gerada
                 parcelada: bool = False,
                 parcelas: int = 1,
                 parcel_index: Optional[int] = None, # 1, 2, ...
                 parcel_total: Optional[int] = None, # Total de parcelas
                 id: Optional[str] = None):

        if not name:
            raise ValueError("O nome da conta não pode ser vazio.")
        if not parse_month_input(month):
            raise ValueError("Formato de mês inválido (esperado YYYY-MM).")
        if amount_decimal < Decimal("0"):
            raise ValueError("O valor da conta não pode ser negativo.")

        self.id: str = id if id else str(uuid.uuid4())
        self.name: str = name
        self.amount_decimal: Decimal = amount_decimal.quantize(Decimal("0.01"))
        self.month: str = month
        self.category: str = category
        self.notes: str = notes
        self.status: str = status
        self.paid_at: Optional[datetime] = paid_at
        self.paid_amount: Optional[Decimal] = paid_amount.quantize(Decimal("0.01")) if paid_amount else None
        self.created_at: datetime = created_at if created_at else datetime.now()
        self.recorrente: bool = recorrente
        self.rec_type: Optional[str] = rec_type
        self.recorrencia_months: int = max(0, recorrencia_months)
        self.rec_origin: Optional[str] = rec_origin
        self.parcelada: bool = parcelada
        self.parcelas: int = max(1, parcelas)
        self.parcel_index: Optional[int] = parcel_index
        self.parcel_total: Optional[int] = parcel_total

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "amount_decimal": str(self.amount_decimal),
            "month": self.month,
            "category": self.category,
            "notes": self.notes,
            "status": self.status,
            "paid_at": self.paid_at.isoformat() if self.paid_at else None,
            "paid_amount": str(self.paid_amount) if self.paid_amount else None,
            "created_at": self.created_at.isoformat(),
            "recorrente": self.recorrente,
            "rec_type": self.rec_type,
            "recorrencia_months": self.recorrencia_months,
            "rec_origin": self.rec_origin,
            "parcelada": self.parcelada,
            "parcelas": self.parcelas,
            "parcel_index": self.parcel_index,
            "parcel_total": self.parcel_total,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'Conta':
        # CORREÇÃO: Normalização mais cuidadosa dos dados ao carregar
        amount_raw = data.get("amount_decimal") or data.get("valor") or data.get("value") or "0.00"
        
        # Se o valor já é um Decimal ou número, converter para string primeiro
        if isinstance(amount_raw, (Decimal, int, float)):
            amount_raw = str(amount_raw)
        
        amount = money_to_decimal(amount_raw)
        
        # CORREÇÃO: Tratar paid_amount de forma mais cuidadosa
        paid_amount = None
        paid_amount_raw = data.get("paid_amount")
        if paid_amount_raw is not None and paid_amount_raw != "":
            try:
                # Se paid_amount já é um número (Decimal), usar diretamente
                if isinstance(paid_amount_raw, (int, float, Decimal)):
                    paid_amount = Decimal(str(paid_amount_raw)).quantize(Decimal("0.01"))
                else:
                    # Se é string, usar money_to_decimal
                    paid_amount = money_to_decimal(str(paid_amount_raw))
            except (InvalidOperation, ValueError):
                paid_amount = None
        
        created_at_str = data.get("created_at")
        created_at = datetime.fromisoformat(created_at_str) if created_at_str else datetime.now()
        paid_at_str = data.get("paid_at")
        paid_at = datetime.fromisoformat(paid_at_str) if paid_at_str else None

        recorrente = bool(data.get("recorrente") or data.get("rec_type") in ("fixed", "indef") or int(data.get("recorrencia_months", 0) or 0) > 0)
        parcelada = bool(data.get("parcelada") or int(data.get("parcelas", 1) or 1) > 1)

        return Conta(
            id=data.get("id"),
            name=data.get("name") or data.get("title") or "Sem título",
            amount_decimal=amount,
            month=data.get("month") or created_at.strftime("%Y-%m"),
            category=data.get("category") or "Outros",
            notes=data.get("notes", ""),
            status=data.get("status", "pending"),
            paid_at=paid_at,
            paid_amount=paid_amount,
            created_at=created_at,
            recorrente=recorrente,
            rec_type=data.get("rec_type"),
            recorrencia_months=int(data.get("recorrencia_months", 0) or 0),
            rec_origin=data.get("rec_origin"),
            parcelada=parcelada,
            parcelas=int(data.get("parcelas", 1) or 1),
            parcel_index=data.get("parcel_index"),
            parcel_total=data.get("parcel_total")
        )

# ---------- Data Manager (carrega/salva JSON) ----------
class DataManager:
    def __init__(self, file_path: str):
        self.file_path: str = file_path
        # REMOVIDO: _handle_first_run() - não há mais tratamento especial de primeira execução
        self._ensure_datafile()
        self._data: Dict[str, Any] = self._load_from_file()

    def _ensure_datafile(self):
        """Cria o arquivo de dados se não existir."""
        if not os.path.exists(self.file_path):
            base_data = {
                "contas": [],
                "categories": [c.to_dict() for c in self._get_default_categories()]
            }
            with DATA_LOCK:
                with open(self.file_path, "w", encoding="utf-8") as f:
                    json.dump(base_data, f, ensure_ascii=False, indent=2)

    def _get_default_categories(self) -> List[Category]:
        """Retorna as categorias fixas e a padrão 'Outros'."""
        return [Category(c["name"], c["icon"]) for c in FIXED_CATEGORIES_DATA] + [Category(DEFAULT_EXTRA_CATEGORY_DATA["name"], DEFAULT_EXTRA_CATEGORY_DATA["icon"])]

    def _load_from_file(self) -> Dict[str, Any]:
        """Carrega os dados do arquivo JSON e normaliza para objetos."""
        self._ensure_datafile()
        with DATA_LOCK:
            with open(self.file_path, "r", encoding="utf-8") as f:
                try:
                    raw_data = json.load(f)
                except json.JSONDecodeError:
                    raw_data = {"contas": [], "categories": []}

        # Normalizar categorias
        loaded_cats_dict = {c["name"]: Category.from_dict(c) for c in raw_data.get("categories", []) if isinstance(c, dict) and c.get("name")}
        normalized_categories: List[Category] = []
        seen_cat_names = set()

        # Garantir categorias fixas primeiro
        for fc in self._get_default_categories():
            if fc.name not in seen_cat_names:
                normalized_categories.append(fc)
                seen_cat_names.add(fc.name)

        # Adicionar outras categorias carregadas que não são fixas
        for cat_name, cat_obj in loaded_cats_dict.items():
            if cat_name not in seen_cat_names:
                normalized_categories.append(cat_obj)
                seen_cat_names.add(cat_name)

        # Normalizar contas
        normalized_contas: List[Conta] = []
        for c_data in raw_data.get("contas", []):
            try:
                normalized_contas.append(Conta.from_dict(c_data))
            except (ValueError, InvalidOperation) as e:
                app.logger.warning(f"Erro ao carregar conta: {c_data}. Ignorando. Erro: {e}")

        return {
            "contas": normalized_contas,
            "categories": normalized_categories
        }

    def _save_to_file(self):
        """Salva os dados (objetos) de volta para o arquivo JSON."""
        serializable_data = {
            "contas": [c.to_dict() for c in self._data["contas"]],
            "categories": [c.to_dict() for c in self._data["categories"]]
        }
        with DATA_LOCK:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(serializable_data, f, ensure_ascii=False, indent=2)

    @property
    def contas(self) -> List[Conta]:
        return self._data.get("contas", [])

    @contas.setter
    def contas(self, new_contas: List[Conta]):
        self._data["contas"] = new_contas
        self._save_to_file()

    @property
    def categories(self) -> List[Category]:
        return self._data.get("categories", [])

    @categories.setter
    def categories(self, new_categories: List[Category]):
        self._data["categories"] = new_categories
        self._save_to_file()

    def get_conta_by_id(self, conta_id: str) -> Optional[Conta]:
        """Retorna uma Conta pelo ID."""
        return next((c for c in self.contas if c.id == conta_id), None)

    def add_conta(self, conta: Conta):
        """Adiciona uma nova conta."""
        self.contas.append(conta)
        self._save_to_file()

    def update_conta(self, updated_conta: Conta):
        """Atualiza uma conta existente."""
        for i, c in enumerate(self.contas):
            if c.id == updated_conta.id:
                self.contas[i] = updated_conta
                self._save_to_file()
                return
        raise ValueError(f"Conta com ID {updated_conta.id} não encontrada para atualização.")

    def delete_conta(self, conta_id: str):
        """Exclui uma conta pelo ID."""
        initial_count = len(self.contas)
        self.contas = [c for c in self.contas if c.id != conta_id]
        if len(self.contas) == initial_count:
            raise ValueError(f"Conta com ID {conta_id} não encontrada para exclusão.")
        self._save_to_file()

    def add_category(self, category: Category):
        """Adiciona uma nova categoria, verificando duplicatas."""
        if any(c.name.lower() == category.name.lower() for c in self.categories):
            raise ValueError(f"Categoria '{category.name}' já existe.")
        self.categories.append(category)
        self._save_to_file()

    def ensure_recurring_for_month(self, month_key: str):
        """Gera instâncias recorrentes para o mês especificado."""
        contas_to_add: List[Conta] = []
        for origin_conta in self.contas:
            if origin_conta.rec_type in ("indef", "fixed") and not origin_conta.rec_origin:
                origin_id = origin_conta.id
                rec_type = origin_conta.rec_type
                rec_months = origin_conta.recorrencia_months

                # Verificar se a conta original é anterior ao mês alvo
                try:
                    origin_date = parse_month_input(origin_conta.month)
                    target_date = parse_month_input(month_key)
                    if not origin_date or not target_date or target_date < origin_date:
                        continue
                except Exception:
                    continue

                # Evitar duplicatas (verificar se já existe uma recorrência gerada para este mês e esta origem)
                exists = any(
                    (c.month == month_key) and (
                        c.rec_origin == origin_id or # preferencialmente por rec_origin
                        (not c.rec_origin and c.name == origin_conta.name and c.month == origin_conta.month and c.id != origin_id) # fallback para nome/mes se rec_origin nao existir
                    )
                    for c in self.contas
                )
                if exists:
                    continue

                if rec_type == "indef":
                    # Gera a próxima fatura com valor 0
                    inst_month = add_months(parse_month_input(origin_conta.month), 1)
                    if month_key_from_date(inst_month) == month_key: # Garante que estamos gerando apenas a próxima
                        new_conta = Conta(
                            name=origin_conta.name,
                            amount_decimal=Decimal("0.00"),
                            month=month_key,
                            category=origin_conta.category,
                            notes=origin_conta.notes,
                            recorrente=True,
                            rec_type="indef",
                            rec_origin=origin_id,
                            parcelada=False,
                            parcelas=1
                        )
                        contas_to_add.append(new_conta)

                elif rec_type == "fixed" and rec_months > 0:
                    origin_date = parse_month_input(origin_conta.month)
                    if not origin_date: continue

                    for i in range(1, rec_months): # Gera cópias para os próximos `recorrencia_months - 1` meses
                        next_date = add_months(origin_date, i)
                        next_month_key = month_key_from_date(next_date)
                        if next_month_key == month_key:
                            # Pegar valor do mês anterior se existir, senão usa o valor da origem
                            prev_month_val = origin_conta.amount_decimal
                            prev_date_for_value = add_months(next_date, -1)
                            prev_month_key_for_value = month_key_from_date(prev_date_for_value)
                            
                            # Tentar encontrar a instância da conta para o mês anterior (da mesma origem ou nome)
                            prev_inst = next((
                                c for c in self.contas
                                if c.month == prev_month_key_for_value and (
                                    c.rec_origin == origin_id or
                                    (not c.rec_origin and c.name == origin_conta.name and c.month == origin_conta.month)
                                )
                            ), None)

                            if prev_inst:
                                prev_month_val = prev_inst.amount_decimal

                            # Verificar se esta instância fixa já existe para o mês alvo
                            fixed_exists = any(
                                (c.month == month_key) and (
                                    c.rec_origin == origin_id or
                                    (not c.rec_origin and c.name == origin_conta.name and c.month == origin_conta.month)
                                )
                                for c in self.contas
                            )
                            if fixed_exists: continue

                            new_conta = Conta(
                                name=origin_conta.name,
                                amount_decimal=prev_month_val,
                                month=month_key,
                                category=origin_conta.category,
                                notes=origin_conta.notes,
                                recorrente=True,
                                rec_type="fixed",
                                recorrencia_months=rec_months,
                                rec_origin=origin_id,
                                parcelada=False,
                                parcelas=1
                            )
                            contas_to_add.append(new_conta)

        if contas_to_add:
            self._data["contas"].extend(contas_to_add)
            self._save_to_file()

# Inicializa o DataManager
data_manager = DataManager(DATA_FILE)

# Garantir recorrências para o mês atual ao iniciar a aplicação
try:
    data_manager.ensure_recurring_for_month(date.today().strftime("%Y-%m"))
except Exception as e:
    app.logger.error(f"Erro ao gerar recorrências iniciais: {e}")

# ---------- Rotas ----------
@app.route("/", methods=["GET"])
def index():
    sel_month = request.args.get("month") or date.today().strftime("%Y-%m")
    sel_category_name = request.args.get("category") or "Todos"
    q_search = (request.args.get("q") or "").strip().lower()

    # Gerar recorrências para o mês selecionado e o mês atual
    try:
        data_manager.ensure_recurring_for_month(sel_month)
        data_manager.ensure_recurring_for_month(date.today().strftime("%Y-%m"))
    except Exception as e:
        flash(f"Erro ao gerar recorrências: {e}", "danger")

    contas = data_manager.contas
    categories = data_manager.categories

    # Filtrar e ordenar contas
    contas_mes: List[Conta] = []
    for c in contas:
        if c.month == sel_month:
            if sel_category_name == "Todos" or c.category == sel_category_name:
                if q_search in (c.name.lower() + " " + c.notes.lower()):
                    contas_mes.append(c)
    contas_mes.sort(key=lambda c: (c.created_at.isoformat(), c.name))

    def totals_for_month(month_key: str) -> Dict[str, Any]:
        total = Decimal("0")
        paid = Decimal("0")
        pending = Decimal("0")
        by_cat: Dict[str, Decimal] = {cat.name: Decimal("0") for cat in categories}
        if DEFAULT_EXTRA_CATEGORY_DATA["name"] not in by_cat: # Garante 'Outros' existe
            by_cat[DEFAULT_EXTRA_CATEGORY_DATA["name"]] = Decimal("0")

        for c in contas:
            if c.month == month_key:
                val = c.amount_decimal
                total += val
                cat_name = c.category if c.category in by_cat else DEFAULT_EXTRA_CATEGORY_DATA["name"]
                by_cat[cat_name] += val
                if c.status == "paid":
                    # CORREÇÃO: Usar o paid_amount se existir, senão usar o valor original
                    paid_amount_val = c.paid_amount if c.paid_amount is not None else val
                    paid += paid_amount_val
                else:
                    pending += val
        return {"total": total, "paid": paid, "pending": pending, "by_category": by_cat}

    curr_totals = totals_for_month(sel_month)
    
    prev_month_key: Optional[str] = None
    prev_totals: Dict[str, Any] = {"total": Decimal("0"), "paid": Decimal("0"), "pending": Decimal("0"), "by_category": {}}
    
    try:
        y, m = map(int, sel_month.split("-"))
        prev_dt = add_months(date(y, m, 1), -1)
        prev_month_key = month_key_from_date(prev_dt)
        prev_totals = totals_for_month(prev_month_key)
    except Exception:
        pass # Caso o mês selecionado seja o primeiro mês com dados ou haja erro na data.

    diff = curr_totals["total"] - prev_totals["total"]
    percent: Optional[Decimal] = None
    try:
        if prev_totals["total"] != Decimal("0"):
            percent = (diff / prev_totals["total"] * 100).quantize(Decimal("0.1"))
    except Exception:
        pass

    all_months = sorted({c.month for c in contas if c.month} | {date.today().strftime("%Y-%m")}, reverse=True)
    cat_colors = {c.name: color_for_category(c.name) for c in categories}
    cat_colors[DEFAULT_EXTRA_CATEGORY_DATA["name"]] = color_for_category(DEFAULT_EXTRA_CATEGORY_DATA["name"]) # Garante cor para "Outros"

    return render_template_string(TEMPLATE_INDEX,
        contas=contas_mes,
        sel_month=sel_month,
        months=all_months,
        categories=["Todos"] + [c.name for c in categories],
        categories_full=categories, # Objetos Category para template
        sel_category=sel_category_name,
        q_search=q_search,
        curr_totals=curr_totals,
        prev_totals=prev_totals,
        prev_month_key=prev_month_key,
        diff=diff,
        percent=percent,
        decimal_to_brl=decimal_to_brl,
        cat_colors=cat_colors
    )

@app.route("/cadastrar", methods=["GET", "POST"])
def cadastrar():
    categories = data_manager.categories
    if request.method == "POST":
        name = request.form.get("name","").strip()
        valor_raw = request.form.get("value","").strip()
        mes_input = request.form.get("mes") or date.today().strftime("%Y-%m")
        category_name = request.form.get("category") or DEFAULT_EXTRA_CATEGORY_DATA["name"]
        notes = request.form.get("notes","").strip()

        recorr_indef = True if request.form.get("recorrente_indef") == "on" else False
        recorrencia_months: int = int(request.form.get("recorrencia_months", 0) or 0)
        parcelada = True if request.form.get("parcelada") == "on" else False
        parcelas: int = int(request.form.get("parcelas", 1) or 1)

        try:
            value = money_to_decimal(valor_raw)
        except InvalidOperation:
            flash("Valor inválido. Use formato numérico (ex: 150,50 ou 150.50).", "danger")
            return redirect(url_for("cadastrar"))

        mes_date = parse_month_input(mes_input)
        if not mes_date:
            flash("Mês inválido.", "danger")
            return redirect(url_for("cadastrar"))
        month_key = month_key_from_date(mes_date)

        rec_type: Optional[str] = None
        if recorr_indef:
            rec_type = "indef"
        elif recorrencia_months > 0:
            rec_type = "fixed"

        try:
            new_conta = Conta(
                name=name,
                amount_decimal=value,
                month=month_key,
                category=category_name,
                notes=notes,
                recorrente=bool(rec_type),
                rec_type=rec_type,
                recorrencia_months=recorrencia_months,
                parcelada=parcelada,
                parcelas=parcelas
            )
            data_manager.add_conta(new_conta)

            # Lógica de parcelamento
            if parcelada and parcelas > 1:
                parts = split_amount_into_installments(value, parcelas)
                # Atualiza a primeira parcela que já foi adicionada
                new_conta.amount_decimal = parts[0]
                new_conta.parcel_index = 1
                new_conta.parcel_total = parcelas
                data_manager.update_conta(new_conta)

                # Gera parcelas futuras
                for i in range(1, parcelas):
                    next_dt = add_months(mes_date, i)
                    next_month_key = month_key_from_date(next_dt)
                    installment_conta = Conta(
                        name=name,
                        amount_decimal=parts[i],
                        month=next_month_key,
                        category=category_name,
                        notes=notes,
                        parcelada=True,
                        parcelas=parcelas,
                        parcel_index=i+1,
                        parcel_total=parcelas
                    )
                    data_manager.add_conta(installment_conta)

            # Lógica de recorrência fixa (gerar cópias futuras com valor igual)
            if rec_type == "fixed" and recorrencia_months > 0:
                # O ID da conta original é o "rec_origin" para as futuras
                new_conta.rec_origin = new_conta.id
                data_manager.update_conta(new_conta) # Salva a origem com seu próprio ID
                
                for i in range(1, recorrencia_months):
                    next_dt = add_months(mes_date, i)
                    next_month_key = month_key_from_date(next_dt)
                    recurring_conta = Conta(
                        name=name,
                        amount_decimal=value, # Valor da conta original
                        month=next_month_key,
                        category=category_name,
                        notes=notes,
                        recorrente=True,
                        rec_type="fixed",
                        recorrencia_months=recorrencia_months,
                        rec_origin=new_conta.id, # Linka à conta original
                        parcelada=False,
                        parcelas=1
                    )
                    data_manager.add_conta(recurring_conta)
            
            # Lógica de recorrência indefinida (gera próxima com valor 0)
            elif rec_type == "indef":
                new_conta.rec_origin = new_conta.id
                data_manager.update_conta(new_conta) # Salva a origem com seu próprio ID

                next_dt = add_months(mes_date, 1)
                next_month_key = month_key_from_date(next_dt)
                indef_recurring_conta = Conta(
                    name=name,
                    amount_decimal=Decimal("0.00"),
                    month=next_month_key,
                    category=category_name,
                    notes=notes,
                    recorrente=True,
                    rec_type="indef",
                    rec_origin=new_conta.id, # Linka à conta original
                    parcelada=False,
                    parcelas=1
                )
                data_manager.add_conta(indef_recurring_conta)

            flash("Conta cadastrada com sucesso.", "success")
            return redirect(url_for("cadastrar")) # Redireciona para um formulário limpo

        except ValueError as e:
            flash(f"Erro ao cadastrar conta: {e}", "danger")
            # Permite ao usuário corrigir e reenviar, talvez pré-preenchendo o form com request.form
            # Para este exemplo, apenas redireciona para um form vazio
            return redirect(url_for("cadastrar"))

    default_mes = date.today().strftime("%Y-%m")
    empty_form_data: Dict[str, Any] = {
        "id": None, "name": "", "value": "", "mes": default_mes,
        "category": DEFAULT_EXTRA_CATEGORY_DATA["name"], "notes": "",
        "recorrente_indef": False, "recorrencia_months": 0,
        "parcelada": False, "parcelas": 1
    }
    return render_template_string(TEMPLATE_CADASTRAR, categories=categories, form=empty_form_data)

@app.route("/edit/<string:conta_id>", methods=["GET", "POST"])
def edit(conta_id: str):
    target_conta = data_manager.get_conta_by_id(conta_id)
    if not target_conta:
        flash("Conta não encontrada.", "danger")
        return redirect(url_for("index"))

    categories = data_manager.categories

    if request.method == "POST":
        name = request.form.get("name","").strip()
        valor_raw = request.form.get("value","").strip()
        mes_input = request.form.get("mes") or target_conta.month
        category_name = request.form.get("category") or target_conta.category
        notes = request.form.get("notes","").strip()

        recorr_indef = True if request.form.get("recorrente_indef") == "on" else False
        recorrencia_months: int = int(request.form.get("recorrencia_months", 0) or 0)
        parcelada = True if request.form.get("parcelada") == "on" else False
        parcelas: int = int(request.form.get("parcelas", 1) or 1)

        try:
            value = money_to_decimal(valor_raw)
        except InvalidOperation:
            flash("Valor inválido. Use formato numérico (ex: 150,50 ou 150.50).", "danger")
            return redirect(url_for("edit", conta_id=conta_id))

        mes_date = parse_month_input(mes_input)
        if not mes_date:
            flash("Mês inválido.", "danger")
            return redirect(url_for("edit", conta_id=conta_id))
        month_key = month_key_from_date(mes_date)

        rec_type: Optional[str] = None
        if recorr_indef:
            rec_type = "indef"
        elif recorrencia_months > 0:
            rec_type = "fixed"

        try:
            # Atualiza os atributos do objeto target_conta
            target_conta.name = name
            target_conta.amount_decimal = value
            target_conta.month = month_key
            target_conta.category = category_name
            target_conta.notes = notes
            target_conta.recorrente = bool(rec_type)
            target_conta.rec_type = rec_type
            target_conta.recorrencia_months = recorrencia_months
            target_conta.parcelada = parcelada
            target_conta.parcelas = parcelas
            
            # TODO: Lógica de atualização para parcelamento/recorrência em edição é complexa.
            # Se uma conta parcelada/recorrente é editada, suas "irmãs" podem precisar ser atualizadas ou excluídas.
            # Por simplicidade, esta versão apenas atualiza a conta específica.
            # Para uma solução completa, seria necessário:
            # 1. Identificar se a conta é uma origem ou uma parcela/recorrência.
            # 2. Se for origem, perguntar ao usuário se deseja atualizar todas as relacionadas.
            # 3. Implementar a lógica para encontrar e atualizar/excluir as contas relacionadas.

            data_manager.update_conta(target_conta)
            flash("Conta atualizada com sucesso.", "success")
            return redirect(url_for("index", month=month_key))

        except ValueError as e:
            flash(f"Erro ao atualizar conta: {e}", "danger")
            return redirect(url_for("edit", conta_id=conta_id))

    # GET -> pré-preencher formulário com dados da conta
    form_data: Dict[str, Any] = {
        "id": target_conta.id,
        "name": target_conta.name,
        "value": str(target_conta.amount_decimal),
        "mes": target_conta.month,
        "category": target_conta.category,
        "notes": target_conta.notes,
        "recorrente_indef": target_conta.rec_type == "indef",
        "recorrencia_months": target_conta.recorrencia_months,
        "parcelada": target_conta.parcelada,
        "parcelas": target_conta.parcelas
    }
    return render_template_string(TEMPLATE_CADASTRAR, categories=categories, form=form_data)

@app.route("/toggle_pay/<string:conta_id>", methods=["POST"])
def toggle_pay(conta_id: str):
    target_conta = data_manager.get_conta_by_id(conta_id)
    if not target_conta:
        flash("Conta não encontrada.", "danger")
        return redirect(url_for("index", month=request.args.get("month") or date.today().strftime("%Y-%m")))

    original_month = target_conta.month

    if target_conta.status == "paid":
        target_conta.status = "pending"
        target_conta.paid_at = None
        target_conta.paid_amount = None
        flash("Pagamento desfeito (voltou a pendente).", "info")
    else:
        paid_amount_raw = request.form.get("paid_amount")
        paid_date_raw = request.form.get("paid_date")

        paid_amount: Optional[Decimal] = None
        if paid_amount_raw and paid_amount_raw.strip():
            try:
                paid_amount = money_to_decimal(paid_amount_raw.strip())
            except InvalidOperation:
                flash("Valor de pagamento inválido.", "danger")
                return redirect(url_for("index", month=original_month))
        
        # CORREÇÃO: Se não foi informado valor pago, usar o valor original da conta
        target_conta.paid_amount = paid_amount if paid_amount is not None else target_conta.amount_decimal
        
        if paid_date_raw:
            try:
                target_conta.paid_at = datetime.fromisoformat(paid_date_raw)
            except ValueError: # Invalid date format
                target_conta.paid_at = datetime.now()
        else:
            target_conta.paid_at = datetime.now()
        target_conta.status = "paid"
        flash("Conta marcada como paga.", "success")

    try:
        data_manager.update_conta(target_conta)
    except ValueError as e:
        flash(f"Erro ao atualizar status da conta: {e}", "danger")
        
    return redirect(url_for("index", month=request.args.get("month") or original_month))

@app.route("/delete/<string:conta_id>", methods=["POST"])
def delete(conta_id: str):
    original_month: Optional[str] = None
    target_conta = data_manager.get_conta_by_id(conta_id)
    if target_conta:
        original_month = target_conta.month

    try:
        data_manager.delete_conta(conta_id)
        flash("Conta excluída.", "warning")
    except ValueError:
        flash("Conta não encontrada.", "danger")
        
    return redirect(url_for("index", month=request.args.get("month") or original_month or date.today().strftime("%Y-%m")))

@app.route("/categories", methods=["GET"])
def categories_view():
    categories = data_manager.categories
    cat_colors = {c.name: color_for_category(c.name) for c in categories}
    return render_template_string(TEMPLATE_CATEGORIES, categories=categories, cat_colors=cat_colors)

@app.route("/add_category", methods=["POST"])
def add_category():
    new_cat_name = (request.form.get("new_category") or "").strip()
    icon = (request.form.get("icon_choice") or "").strip() or "📂"

    if not new_cat_name:
        flash("Nome de categoria vazio.", "danger")
        return redirect(request.referrer or url_for("categories_view"))

    fixed_names = {c["name"] for c in FIXED_CATEGORIES_DATA}
    if new_cat_name in fixed_names:
        flash("Nome de categoria reservado (fixo). Escolha outro nome.", "warning")
        return redirect(request.referrer or url_for("categories_view"))

    try:
        new_category = Category(name=new_cat_name, icon=icon)
        data_manager.add_category(new_category)
        flash(f"Categoria '{new_cat_name}' adicionada.", "success")
    except ValueError as e:
        flash(f"Erro ao adicionar categoria: {e}", "danger")
        
    return redirect(request.referrer or url_for("categories_view"))

@app.route("/chart_data")
def chart_data():
    month = request.args.get("month") or date.today().strftime("%Y-%m")
    
    # Garantir recorrências para o mês do gráfico
    try:
        data_manager.ensure_recurring_for_month(month)
    except Exception as e:
        app.logger.error(f"Erro ao gerar recorrências para o gráfico: {e}")

    contas = data_manager.contas
    categories = data_manager.categories
    
    by_cat: Dict[str, Decimal] = {c.name: Decimal("0") for c in categories}
    by_cat[DEFAULT_EXTRA_CATEGORY_DATA["name"]] = by_cat.get(DEFAULT_EXTRA_CATEGORY_DATA["name"], Decimal("0"))

    for c in contas:
        if c.month == month:
            val = c.amount_decimal
            cat_name = c.category if c.category in by_cat else DEFAULT_EXTRA_CATEGORY_DATA["name"]
            by_cat[cat_name] += val
    
    # Filtrar categorias com valor zero para o gráfico ficar mais limpo
    labels = []
    values = []
    colors = []
    for cat_name, val in by_cat.items():
        if val > Decimal("0"):
            labels.append(cat_name)
            values.append(float(val))
            colors.append(color_for_category(cat_name))

    return jsonify({"labels": labels, "values": values, "colors": colors, "month": month})

# ---------- Templates (inline) ----------
# TEMA MODERNO: Interface repaginada com design contemporâneo
TEMPLATE_INDEX = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Organizador de Contas</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    :root {
      --primary-dark: #1a1a2e;
      --secondary-dark: #16213e;
      --accent-blue: #0f3460;
      --bright-blue: #533483;
      --neon-cyan: #00d4ff;
      --soft-white: #f8f9fa;
      --success-green: #28a745;
      --danger-red: #dc3545;
      --warning-orange: #fd7e14;
      --gradient-bg: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      --card-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
      --hover-shadow: 0 15px 40px rgba(0, 0, 0, 0.25);
    }
    
    body {
      background: var(--gradient-bg);
      min-height: 100vh;
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    .navbar {
      background: rgba(26, 26, 46, 0.95) !important;
      backdrop-filter: blur(10px);
      border-bottom: 2px solid var(--neon-cyan);
    }
    
    .brand {
      color: var(--neon-cyan) !important;
      font-weight: 700;
      font-size: 1.5rem;
      text-shadow: 0 0 10px rgba(0, 212, 255, 0.3);
    }
    
    .modern-card {
      background: rgba(255, 255, 255, 0.95);
      border-radius: 20px;
      box-shadow: var(--card-shadow);
      border: 1px solid rgba(255, 255, 255, 0.2);
      backdrop-filter: blur(10px);
      transition: all 0.3s ease;
    }
    
    .modern-card:hover {
      box-shadow: var(--hover-shadow);
      transform: translateY(-5px);
    }
    
    .btn-modern {
      background: linear-gradient(45deg, var(--bright-blue), var(--neon-cyan));
      color: white;
      border: none;
      border-radius: 15px;
      padding: 12px 25px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      transition: all 0.3s ease;
      box-shadow: 0 5px 15px rgba(83, 52, 131, 0.3);
    }
    
    .btn-modern:hover {
      transform: translateY(-2px);
      box-shadow: 0 8px 25px rgba(83, 52, 131, 0.4);
      color: white;
    }
    
    .btn-outline-modern {
      border: 2px solid var(--neon-cyan);
      color: var(--neon-cyan);
      background: transparent;
      border-radius: 15px;
      padding: 10px 20px;
      font-weight: 600;
      transition: all 0.3s ease;
    }
    
    .btn-outline-modern:hover {
      background: var(--neon-cyan);
      color: white;
      transform: translateY(-2px);
    }
    
    .status-paid {
      background: linear-gradient(45deg, var(--success-green), #20c997);
      color: white;
      padding: 8px 16px;
      border-radius: 20px;
      font-weight: 600;
      text-transform: uppercase;
      font-size: 0.8rem;
      letter-spacing: 0.5px;
    }
    
    .status-pending {
      background: linear-gradient(45deg, var(--danger-red), #e74c3c);
      color: white;
      padding: 8px 16px;
      border-radius: 20px;
      font-weight: 600;
      text-transform: uppercase;
      font-size: 0.8rem;
      letter-spacing: 0.5px;
    }
    
    .form-control, .form-select {
      border-radius: 15px;
      border: 2px solid rgba(0, 212, 255, 0.3);
      padding: 12px 20px;
      transition: all 0.3s ease;
    }
    
    .form-control:focus, .form-select:focus {
      border-color: var(--neon-cyan);
      box-shadow: 0 0 20px rgba(0, 212, 255, 0.2);
    }
    
    .table {
      background: rgba(255, 255, 255, 0.9);
      border-radius: 15px;
      overflow: hidden;
    }
    
    .table thead th {
      background: linear-gradient(45deg, var(--primary-dark), var(--secondary-dark));
      color: white;
      border: none;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }
    
    .table tbody tr {
      transition: all 0.3s ease;
    }
    
    .table tbody tr:hover {
      background: rgba(0, 212, 255, 0.1);
      transform: scale(1.02);
    }
    
    .stats-card {
      background: linear-gradient(135deg, rgba(255, 255, 255, 0.9), rgba(255, 255, 255, 0.7));
      border-radius: 20px;
      padding: 25px;
      text-align: center;
      border: 1px solid rgba(255, 255, 255, 0.3);
      transition: all 0.3s ease;
    }
    
    .stats-card:hover {
      transform: translateY(-5px);
      box-shadow: 0 15px 30px rgba(0, 0, 0, 0.2);
    }
    
    .stats-value {
      font-size: 2rem;
      font-weight: 700;
      margin-top: 10px;
    }
    
    .stats-label {
      color: #6c757d;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      font-size: 0.9rem;
    }
    
    .modal-content {
      border-radius: 20px;
      border: none;
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
    }
    
    .modal-header {
      background: linear-gradient(45deg, var(--primary-dark), var(--secondary-dark));
      color: white;
      border-radius: 20px 20px 0 0;
    }
    
    .arrow-icon {
      display: inline-block;
      width: 1.5em;
      height: 1.5em;
      vertical-align: text-bottom;
      background-repeat: no-repeat;
      background-position: center;
      background-size: 100%;
    }
    
    .arrow-up {
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath fill='%23dc3545' d='M7.247 4.86A.75.75 0 018 4.5h.5a.75.75 0 01.753.36l2.5 4.5A.75.75 0 0111.5 10H10a.75.75 0 01-.703-.496L8 6.072l-1.297 3.432A.75.75 0 016 10H4.5a.75.75 0 01-.753-1.14L7.247 4.86z'/%3E%3C/svg%3E");
    }
    
    .arrow-down {
      background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Cpath fill='%2328a745' d='M8.753 11.14A.75.75 0 018 11.5h-.5a.75.75 0 01-.753-.36L4.247 6.64A.75.75 0 014.5 6H6a.75.75 0 01.703.496L8 9.928l1.297-3.432A.75.75 0 0110 6h1.5a.75.75 0 01.753 1.14L8.753 11.14z'/%3E%3C/svg%3E");
    }
    
    .text-glow {
      text-shadow: 0 0 10px rgba(0, 212, 255, 0.5);
    }
    
    @keyframes pulse {
      0% { box-shadow: 0 0 0 0 rgba(0, 212, 255, 0.7); }
      70% { box-shadow: 0 0 0 10px rgba(0, 212, 255, 0); }
      100% { box-shadow: 0 0 0 0 rgba(0, 212, 255, 0); }
    }
    
    .pulse-effect {
      animation: pulse 2s infinite;
    }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg">
  <div class="container">
    <a class="navbar-brand brand" href="{{ url_for('index') }}">💎 Organizador de Contas</a>
    <div class="d-flex gap-3">
      <a class="btn btn-outline-modern" href="{{ url_for('cadastrar') }}">➕ Nova Conta</a>
      <a class="btn btn-outline-modern" href="{{ url_for('categories_view') }}">📂 Categorias</a>
    </div>
  </div>
</nav>

<div class="container py-4">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <div class="mb-4">
      {% for cat, msg in messages %}
        <div class="alert alert-{{ 'info' if cat=='info' else cat }} alert-dismissible fade show modern-card" role="alert">
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
      </div>
    {% endif %}
  {% endwith %}

  <!-- Estatísticas -->
  <div class="row mb-4">
    <div class="col-md-3 mb-3">
      <div class="stats-card">
        <div class="stats-label">💰 Total</div>
        <div class="stats-value text-primary">{{ decimal_to_brl(curr_totals.total) }}</div>
      </div>
    </div>
    <div class="col-md-3 mb-3">
      <div class="stats-card">
        <div class="stats-label">✅ Pago</div>
        <div class="stats-value text-success">{{ decimal_to_brl(curr_totals.paid) }}</div>
      </div>
    </div>
    <div class="col-md-3 mb-3">
      <div class="stats-card">
        <div class="stats-label">⏳ Pendente</div>
        <div class="stats-value text-danger">{{ decimal_to_brl(curr_totals.pending) }}</div>
      </div>
    </div>
    <div class="col-md-3 mb-3">
      <div class="stats-card">
        <div class="stats-label">📊 Variação</div>
        <div class="stats-value">
          {% if diff > 0 %}
            <span class="text-danger">+{{ (diff / prev_totals.total * 100).quantize(Decimal('0.1')) if prev_totals.total != 0 else 0 }}%</span>
            <span class="arrow-icon arrow-up"></span>
          {% elif diff < 0 %}
            <span class="text-success">{{ (diff / prev_totals.total * 100).quantize(Decimal('0.1')) if prev_totals.total != 0 else 0 }}%</span>
            <span class="arrow-icon arrow-down"></span>
          {% else %}
            <span class="text-muted">0%</span>
          {% endif %}
        </div>
      </div>
    </div>
  </div>

  <div class="row">
    <div class="col-lg-8">
      <div class="modern-card p-4 mb-4">
        <div class="d-flex justify-content-between align-items-center mb-3">
          <div>
            <h4 class="mb-0 text-glow">📋 Contas - {{ sel_month }}</h4>
          </div>
          <div class="d-flex gap-2 align-items-center">
            <form method="get" class="d-flex gap-2 align-items-center">
              <button type="button" class="btn btn-outline-modern btn-sm" onclick="changeMonth('prev')">←</button>
              <select id="monthSelect" name="month" class="form-select form-select-sm" onchange="this.form.submit()">
                {% for m in months %}
                  <option value="{{ m }}" {% if m==sel_month %}selected{% endif %}>{{ m }}</option>
                {% endfor %}
              </select>
              <button type="button" class="btn btn-outline-modern btn-sm" onclick="changeMonth('next')">→</button>
              <input type="hidden" name="category" value="{{ sel_category }}">
              <input type="hidden" name="q" value="{{ q_search }}">
            </form>
          </div>
        </div>

        <div class="d-flex gap-3 mb-4">
          <select id="filterCategory" name="category" class="form-select" onchange="onFilterChange()">
            {% for cat in categories %}
              <option value="{{ cat }}" {% if cat==sel_category %}selected{% endif %}>{{ cat }}</option>
            {% endfor %}
          </select>
          <input id="searchBox" type="search" class="form-control" placeholder="🔍 Buscar por nome ou nota..." value="{{ q_search }}" oninput="onFilterChange()">
        </div>

        {% if contas %}
        <div class="table-responsive">
          <table id="contasTable" class="table align-middle">
            <thead>
              <tr>
                <th>📝 Nome</th>
                <th>📂 Categoria</th>
                <th>💰 Valor</th>
                <th>📊 Status</th>
                <th class="text-end">⚙️ Ações</th>
              </tr>
            </thead>
            <tbody>
              {% for c in contas %}
              <tr data-name="{{ (c.name + ' ' + (c.notes or '') ).lower() | e }}">
                <td>
                  <strong>{{ c.name }}</strong>
                  {% if c.notes %}<div class="text-muted small">{{ c.notes }}</div>{% endif %}
                </td>
                <td>
                  {% set cat_obj = categories_full | selectattr('name', 'equalto', c.category) | first %}
                  {% if cat_obj %}
                    <span style="font-size:1.2rem">{{ cat_obj.icon }}</span> {{ cat_obj.name }}
                  {% else %}
                    <span>📂 {{ c.category }}</span>
                  {% endif %}
                </td>
                <td><strong>{{ decimal_to_brl(c.amount_decimal) }}</strong></td>
                <td>
                  {% if c.status == 'paid' %}
                    <span class="status-paid">✅ Pago</span>
                    {% if c.paid_at %}<div class="text-muted small">{{ c.paid_at.strftime('%d/%m/%Y') }}</div>{% endif %}
                  {% else %}
                    <span class="status-pending">⏳ Pendente</span>
                  {% endif %}
                  {% if c.recorrente %}
                    <div class="text-muted small mt-1">🔁 Recorrente</div>
                  {% endif %}
                  {% if c.parcelada %}
                    <div class="text-muted small mt-1">📦 {{ c.parcel_index or '?' }}/{{ c.parcel_total or c.parcelas or '?' }}</div>
                  {% endif %}
                </td>
                <td class="text-end">
                  <div class="btn-group" role="group">
                    <a class="btn btn-outline-primary btn-sm" href="{{ url_for('edit', conta_id=c.id, month=sel_month) }}">✏️</a>
                    
                    {% if c.status == 'paid' %}
                      <form method="post" action="{{ url_for('toggle_pay', conta_id=c.id, month=sel_month) }}" style="display:inline">
                        <button class="btn btn-warning btn-sm" type="submit">↩️</button>
                      </form>
                    {% else %}
                      <button class="btn btn-success btn-sm pulse-effect" data-id="{{ c.id }}" data-amount="{{ c.amount_decimal }}" data-month="{{ c.month }}" data-bs-toggle="modal" data-bs-target="#payModal" onclick="openPayModalFromBtn(this)">💵</button>
                    {% endif %}
                    
                    <form method="post" action="{{ url_for('delete', conta_id=c.id, month=sel_month) }}" style="display:inline" onsubmit="return confirm('❌ Tem certeza que deseja excluir esta conta?')">
                      <button class="btn btn-outline-danger btn-sm">🗑️</button>
                    </form>
                  </div>
                </td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
        {% else %}
          <div class="text-center py-5">
            <div style="font-size: 4rem; opacity: 0.3;">📋</div>
            <h5 class="text-muted">Nenhuma conta cadastrada</h5>
            <p class="text-muted">Adicione sua primeira conta para começar!</p>
          </div>
        {% endif %}
      </div>
    </div>

    <div class="col-lg-4">
      <div class="modern-card p-4 mb-4">
        <h5 class="text-glow">📊 Gráfico por Categoria</h5>
        <div class="mb-3">
          <select id="chartMonth" class="form-select" onchange="refreshChart()"></select>
        </div>
        <canvas id="catChart" style="width:100%;height:300px"></canvas>
      </div>

      <div class="modern-card p-4">
        <h5 class="text-glow">🚀 Ações Rápidas</h5>
        <div class="d-grid gap-3 mt-3">
          <a class="btn btn-modern" href="{{ url_for('cadastrar') }}">➕ Nova Conta</a>
          <a class="btn btn-outline-modern" href="{{ url_for('categories_view') }}">📂 Gerenciar Categorias</a>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Modal de Pagamento -->
<div class="modal fade" id="payModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <form id="payForm" method="post" class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">💵 Marcar Pagamento</h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <div class="mb-3">
          <label class="form-label">💰 Valor Pago</label>
          <input name="paid_amount" id="modalPaidAmount" class="form-control" placeholder="Ex: 150.50">
          <div class="form-text">Deixe vazio para usar o valor original</div>
        </div>
        <div class="mb-3">
          <label class="form-label">📅 Data do Pagamento</label>
          <input name="paid_date" id="modalPaidDate" type="date" class="form-control">
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-modern" type="submit">✅ Confirmar</button>
        <button type="button" class="btn btn-outline-modern" data-bs-dismiss="modal">❌ Cancelar</button>
      </div>
    </form>
  </div>
</div>

<footer class="container text-center mt-4 pb-4">
  <div class="modern-card p-3">
    <p class="text-muted mb-0">🔒 Aplicação Local • Dados salvos em <code>dados.json</code></p>
  </div>
</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
  // Popula o seletor de meses do gráfico
  (function populateChartMonths(){
    const sel = document.getElementById('chartMonth');
    sel.innerHTML = '';

    const urlParams = new URLSearchParams(window.location.search);
    const urlMonth = urlParams.get('month');

    const months = new Set();
    const today = new Date();

    for (let i=0; i<12; i++){
      const d = new Date(today.getFullYear(), today.getMonth() - i, 1);
      months.add(d.getFullYear().toString() + '-' + ( (d.getMonth()+1).toString().padStart(2,'0') ));
    }
    
    if (urlMonth && !months.has(urlMonth)) {
      months.add(urlMonth);
    }

    const sortedMonths = Array.from(months).sort().reverse();

    sortedMonths.forEach(m => {
      const opt = document.createElement('option');
      opt.value = m;
      opt.text = m;
      sel.appendChild(opt);
    });

    sel.value = urlMonth || (new Date().getFullYear() + '-' + String(new Date().getMonth()+1).padStart(2,'0'));
  })();

  let catChart = null;
  async function refreshChart(){
    const month = document.getElementById('chartMonth').value;
    const res = await fetch(`/chart_data?month=${encodeURIComponent(month)}`);
    const json = await res.json();
    const labels = json.labels;
    const values = json.values;
    const colors = json.colors;
    const ctx = document.getElementById('catChart').getContext('2d');
    if(catChart) catChart.destroy();
    
    if (values.some(v => v > 0)) {
        catChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
            data: values,
            backgroundColor: colors,
            borderWidth: 3,
            borderColor: '#fff'
            }]
        },
        options: {
            responsive: true,
            plugins: { 
                legend: { 
                    position: 'bottom',
                    labels: {
                        padding: 20,
                        usePointStyle: true
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return context.label + ': R$ ' + context.parsed.toLocaleString('pt-BR', {minimumFractionDigits: 2, maximumFractionDigits: 2});
                        }
                    }
                }
            }
        }
        });
    } else {
        ctx.clearRect(0, 0, ctx.canvas.width, ctx.canvas.height);
        ctx.font = '16px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillStyle = '#666';
        ctx.fillText('📊 Nenhum dado para exibir', ctx.canvas.width / 2, ctx.canvas.height / 2);
    }
  }

  document.addEventListener('DOMContentLoaded', function(){
    refreshChart();
  });

  function onFilterChange(){
    const q = document.getElementById('searchBox').value.toLowerCase();
    const month = document.getElementById('monthSelect').value;
    const cat = document.getElementById('filterCategory').value;
    const params = new URLSearchParams();
    if(month) params.set('month', month);
    if(cat && cat !== 'Todos') params.set('category', cat);
    if(q) params.set('q', q);
    
    window.history.replaceState({}, '', `${location.pathname}?${params.toString()}`);

    const rows = document.querySelectorAll('#contasTable tbody tr');
    rows.forEach(r => {
      const name_and_notes = r.getAttribute('data-name') || '';
      if(name_and_notes.includes(q)) r.style.display = '';
      else r.style.display = 'none';
    });
  }

  let currentPayId = null;
  function openPayModalFromBtn(btn){
    currentPayId = btn.dataset.id;
    document.getElementById('modalPaidAmount').value = btn.dataset.amount;
    
    const today = new Date();
    const year = today.getFullYear();
    const month = String(today.getMonth() + 1).padStart(2, '0');
    const day = String(today.getDate()).padStart(2, '0');
    document.getElementById('modalPaidDate').value = `${year}-${month}-${day}`;

    const form = document.getElementById('payForm');
    form.action = `/toggle_pay/${currentPayId}?month=${encodeURIComponent("{{ sel_month }}")}`;
  }

  function changeMonth(dir){
    const select = document.getElementById('monthSelect');
    let idx = select.selectedIndex;
    if(dir === 'prev') {
      idx = Math.min(select.options.length - 1, idx + 1);
    }
    if(dir === 'next') {
      idx = Math.max(0, idx - 1);
    }
    select.selectedIndex = idx;
    select.form.submit();
  }
</script>
</body>
</html>
"""

TEMPLATE_CATEGORIES = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Gerenciar Categorias</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    :root {
      --primary-dark: #1a1a2e;
      --secondary-dark: #16213e;
      --accent-blue: #0f3460;
      --bright-blue: #533483;
      --neon-cyan: #00d4ff;
      --soft-white: #f8f9fa;
      --gradient-bg: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      --card-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
      --hover-shadow: 0 15px 40px rgba(0, 0, 0, 0.25);
    }
    
    body {
      background: var(--gradient-bg);
      min-height: 100vh;
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    .navbar {
      background: rgba(26, 26, 46, 0.95) !important;
      backdrop-filter: blur(10px);
      border-bottom: 2px solid var(--neon-cyan);
    }
    
    .brand {
      color: var(--neon-cyan) !important;
      font-weight: 700;
      font-size: 1.5rem;
      text-shadow: 0 0 10px rgba(0, 212, 255, 0.3);
    }
    
    .modern-card {
      background: rgba(255, 255, 255, 0.95);
      border-radius: 20px;
      box-shadow: var(--card-shadow);
      border: 1px solid rgba(255, 255, 255, 0.2);
      backdrop-filter: blur(10px);
      transition: all 0.3s ease;
    }
    
    .modern-card:hover {
      box-shadow: var(--hover-shadow);
      transform: translateY(-5px);
    }
    
    .btn-modern {
      background: linear-gradient(45deg, var(--bright-blue), var(--neon-cyan));
      color: white;
      border: none;
      border-radius: 15px;
      padding: 12px 25px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      transition: all 0.3s ease;
      box-shadow: 0 5px 15px rgba(83, 52, 131, 0.3);
    }
    
    .btn-modern:hover {
      transform: translateY(-2px);
      box-shadow: 0 8px 25px rgba(83, 52, 131, 0.4);
      color: white;
    }
    
    .btn-outline-modern {
      border: 2px solid var(--neon-cyan);
      color: var(--neon-cyan);
      background: transparent;
      border-radius: 15px;
      padding: 10px 20px;
      font-weight: 600;
      transition: all 0.3s ease;
    }
    
    .btn-outline-modern:hover {
      background: var(--neon-cyan);
      color: white;
      transform: translateY(-2px);
    }
    
    .category-badge {
      padding: 15px 25px;
      border-radius: 25px;
      font-weight: 600;
      font-size: 1.1rem;
      margin: 8px;
      display: inline-block;
      transition: all 0.3s ease;
      box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
    }
    
    .category-badge:hover {
      transform: translateY(-3px) scale(1.05);
      box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);
    }
    
    .text-glow {
      text-shadow: 0 0 10px rgba(0, 212, 255, 0.5);
    }
    
    .form-control, .form-select {
      border-radius: 15px;
      border: 2px solid rgba(0, 212, 255, 0.3);
      padding: 12px 20px;
      transition: all 0.3s ease;
    }
    
    .form-control:focus, .form-select:focus {
      border-color: var(--neon-cyan);
      box-shadow: 0 0 20px rgba(0, 212, 255, 0.2);
    }
    
    .modal-content {
      border-radius: 20px;
      border: none;
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
    }
    
    .modal-header {
      background: linear-gradient(45deg, var(--primary-dark), var(--secondary-dark));
      color: white;
      border-radius: 20px 20px 0 0;
    }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg">
  <div class="container">
    <a class="navbar-brand brand" href="{{ url_for('index') }}">💎 Organizador de Contas</a>
    <div class="d-flex gap-3">
      <a class="btn btn-outline-modern" href="{{ url_for('cadastrar') }}">➕ Nova Conta</a>
      <button class="btn btn-modern" data-bs-toggle="modal" data-bs-target="#addCategoryModal">🆕 Adicionar Categoria</button>
    </div>
  </div>
</nav>

<div class="container py-4">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <div class="mb-4">
      {% for cat, msg in messages %}
        <div class="alert alert-{{ 'info' if cat=='info' else cat }} alert-dismissible fade show modern-card" role="alert">
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
      </div>
    {% endif %}
  {% endwith %}

  <div class="row justify-content-center">
    <div class="col-lg-10">
      <div class="modern-card p-4 mb-4">
        <h4 class="text-glow mb-4">📂 Categorias Existentes</h4>
        <div class="text-center">
          {% for cat in categories %}
            <span class="category-badge" style="background:{{ cat_colors.get(cat.name) }}; color:#fff;">
              {{ cat.icon }} {{ cat.name }}
            </span>
          {% endfor %}
        </div>
      </div>
      
      <div class="text-center">
        <a class="btn btn-outline-modern btn-lg" href="{{ url_for('index') }}">← Voltar para Início</a>
      </div>
    </div>
  </div>
</div>

<!-- Modal Adicionar Categoria -->
<div class="modal fade" id="addCategoryModal" tabindex="-1" aria-hidden="true">
  <div class="modal-dialog">
    <form method="post" action="{{ url_for('add_category') }}" class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">🆕 Adicionar Nova Categoria</h5>
        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body">
        <div class="mb-3">
          <label class="form-label">📝 Nome da Categoria</label>
          <input name="new_category" class="form-control" placeholder="Ex: Streaming, Academia..." required>
        </div>
        <div class="mb-3">
          <label class="form-label">🎨 Ícone</label>
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
            <option value="✈️">✈️ Viagem</option>
            <option value="🏥">🏥 Saúde</option>
            <option value="📚">📚 Educação</option>
            <option value="🎁">🎁 Presentes</option>
            <option value="🐾">🐾 Pets</option>
            <option value="🏠">🏠 Casa</option>
            <option value="🎉">🎉 Lazer</option>
            <option value="🏋️‍♀️">🏋️‍♀️ Academia</option>
            <option value="💻">💻 Tecnologia</option>
            <option value="💼">💼 Trabalho</option>
            <option value="💰">💰 Investimento</option>
            <option value="💸">💸 Salário</option>
            <option value="🧾">🧾 Outros</option>
          </select>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-modern" type="submit">✅ Adicionar</button>
        <button type="button" class="btn btn-outline-modern" data-bs-dismiss="modal">❌ Cancelar</button>
      </div>
    </form>
  </div>
</div>

<footer class="container text-center mt-4 pb-4">
  <div class="modern-card p-3">
    <p class="text-muted mb-0">🔒 Aplicação Local • Dados salvos em <code>dados.json</code></p>
  </div>
</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
"""

TEMPLATE_CADASTRAR = """
<!doctype html>
<html lang="pt-br">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{% if form.id %}Editar Conta{% else %}Nova Conta{% endif %}</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/css/bootstrap.min.css" rel="stylesheet">
  <style>
    :root {
      --primary-dark: #1a1a2e;
      --secondary-dark: #16213e;
      --accent-blue: #0f3460;
      --bright-blue: #533483;
      --neon-cyan: #00d4ff;
      --soft-white: #f8f9fa;
      --gradient-bg: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      --card-shadow: 0 10px 30px rgba(0, 0, 0, 0.15);
      --hover-shadow: 0 15px 40px rgba(0, 0, 0, 0.25);
    }
    
    body {
      background: var(--gradient-bg);
      min-height: 100vh;
      font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    
    .navbar {
      background: rgba(26, 26, 46, 0.95) !important;
      backdrop-filter: blur(10px);
      border-bottom: 2px solid var(--neon-cyan);
    }
    
    .brand {
      color: var(--neon-cyan) !important;
      font-weight: 700;
      font-size: 1.5rem;
      text-shadow: 0 0 10px rgba(0, 212, 255, 0.3);
    }
    
    .modern-card {
      background: rgba(255, 255, 255, 0.95);
      border-radius: 20px;
      box-shadow: var(--card-shadow);
      border: 1px solid rgba(255, 255, 255, 0.2);
      backdrop-filter: blur(10px);
      transition: all 0.3s ease;
    }
    
    .btn-modern {
      background: linear-gradient(45deg, var(--bright-blue), var(--neon-cyan));
      color: white;
      border: none;
      border-radius: 15px;
      padding: 12px 25px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      transition: all 0.3s ease;
      box-shadow: 0 5px 15px rgba(83, 52, 131, 0.3);
    }
    
    .btn-modern:hover {
      transform: translateY(-2px);
      box-shadow: 0 8px 25px rgba(83, 52, 131, 0.4);
      color: white;
    }
    
    .btn-outline-modern {
      border: 2px solid var(--neon-cyan);
      color: var(--neon-cyan);
      background: transparent;
      border-radius: 15px;
      padding: 10px 20px;
      font-weight: 600;
      transition: all 0.3s ease;
    }
    
    .btn-outline-modern:hover {
      background: var(--neon-cyan);
      color: white;
      transform: translateY(-2px);
    }
    
    .btn-back {
      background: linear-gradient(45deg, #6c757d, #495057);
      color: white;
      border: none;
      border-radius: 25px;
      padding: 10px 20px;
      text-decoration: none;
      font-weight: 600;
      transition: all 0.3s ease;
    }
    
    .btn-back:hover {
      background: linear-gradient(45deg, #495057, #343a40);
      color: white;
      text-decoration: none;
      transform: translateY(-2px);
    }
    
    .form-control, .form-select {
      border-radius: 15px;
      border: 2px solid rgba(0, 212, 255, 0.3);
      padding: 12px 20px;
      transition: all 0.3s ease;
    }
    
    .form-control:focus, .form-select:focus {
      border-color: var(--neon-cyan);
      box-shadow: 0 0 20px rgba(0, 212, 255, 0.2);
    }
    
    .form-check-input:checked {
      background-color: var(--neon-cyan);
      border-color: var(--neon-cyan);
    }
    
    .text-glow {
      text-shadow: 0 0 10px rgba(0, 212, 255, 0.5);
    }
    
    .form-label {
      font-weight: 600;
      color: var(--primary-dark);
      margin-bottom: 8px;
    }
    
    .form-text {
      color: #6c757d;
      font-size: 0.875rem;
    }
  </style>
</head>
<body>
<nav class="navbar navbar-expand-lg">
  <div class="container">
    <div class="d-flex align-items-center gap-3">
      <a class="btn-back" href="{{ url_for('index') }}">← Voltar</a>
      <a class="navbar-brand brand" href="{{ url_for('index') }}">💎 Organizador de Contas</a>
    </div>
  </div>
</nav>

<div class="container py-4">
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
      <div class="mb-4">
      {% for cat, msg in messages %}
        <div class="alert alert-{{ 'info' if cat=='info' else cat }} alert-dismissible fade show modern-card" role="alert">
          {{ msg }}
          <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        </div>
      {% endfor %}
      </div>
    {% endif %}
  {% endwith %}

  <div class="row justify-content-center">
    <div class="col-lg-8">
      <div class="modern-card p-4 mb-4">
        <h4 class="text-glow mb-4">
          {% if form.id %}✏️ Editar Conta{% else %}➕ Nova Conta{% endif %}
        </h4>
        
        <form method="post">
          <div class="row">
            <div class="col-md-6 mb-3">
              <label class="form-label">📝 Nome da Conta</label>
              <input name="name" class="form-control" required placeholder="Ex: Luz, Água, Internet..." autofocus value="{{ form.name }}">
            </div>
            
            <div class="col-md-6 mb-3">
              <label class="form-label">📂 Categoria</label>
              <select name="category" class="form-select" required>
                {% for cat in categories %}
                  <option value="{{ cat.name }}" {% if cat.name == form.category %}selected{% endif %}>{{ cat.icon }} {{ cat.name }}</option>
                {% endfor %}
              </select>
            </div>
          </div>

          <div class="row">
            <div class="col-md-6 mb-3">
              <label class="form-label">💰 Valor</label>
              <input name="value" class="form-control" required placeholder="Ex: 150,50" inputmode="decimal" value="{{ form.value }}">
              <div class="form-text">Use vírgula ou ponto para decimais</div>
            </div>
            
            <div class="col-md-6 mb-3">
              <label class="form-label">📅 Mês de Referência</label>
              <input name="mes" type="month" class="form-control" value="{{ form.mes }}" required>
            </div>
          </div>

          <div class="mb-3">
            <label class="form-label">📝 Observações</label>
            <textarea name="notes" class="form-control" rows="3" placeholder="Observações adicionais...">{{ form.notes }}</textarea>
          </div>

          <hr class="my-4">

          <div class="row">
            <div class="col-md-6">
              <h5 class="text-glow">🔄 Recorrência</h5>
              
              <div class="form-check mb-3">
                <input type="checkbox" class="form-check-input" id="recorrente_indef" name="recorrente_indef" onchange="toggleRecorrenciaOptions()" {% if form.recorrente_indef %}checked{% endif %}>
                <label class="form-check-label" for="recorrente_indef">
                  Recorrente Indefinida
                </label>
                <div class="form-text">Gera próxima fatura com valor R$ 0,00</div>
              </div>

              <div id="recorrenciaMonthsBox" style="display: {% if not form.recorrente_indef %}block{% else %}none{% endif %};">
                <label class="form-label">Recorrência por X meses</label>
                <input name="recorrencia_months" type="number" min="0" max="24" class="form-control" placeholder="Ex: 6" value="{{ form.recorrencia_months }}">
                <div class="form-text">Gera cópias mantendo valor do mês anterior</div>
              </div>
            </div>

            <div class="col-md-6">
              <h5 class="text-glow">📦 Parcelamento</h5>
              
              <div class="form-check mb-3">
                <input type="checkbox" class="form-check-input" id="parcelada" name="parcelada" onchange="toggleParcelas(this)" {% if form.parcelada %}checked{% endif %}>
                <label class="form-check-label" for="parcelada">
                  Conta Parcelada
                </label>
              </div>

              <div id="parcelasBox" style="display: {% if form.parcelada %}block{% else %}none{% endif %};">
                <label class="form-label">Número de Parcelas</label>
                <input name="parcelas" type="number" min="1" max="24" class="form-control" value="{{ form.parcelas or 1 }}">
                <div class="form-text">Valor será dividido automaticamente</div>
              </div>
            </div>
          </div>

          <hr class="my-4">

          <div class="d-flex gap-3 justify-content-end">
            <a class="btn btn-outline-modern" href="{{ url_for('index') }}">❌ Cancelar</a>
            <button class="btn btn-modern" type="submit">
              {% if form.id %}✅ Atualizar{% else %}💾 Salvar{% endif %}
            </button>
          </div>
        </form>
      </div>

      <!-- Adicionar Categoria Rápida -->
      <div class="modern-card p-4">
        <h5 class="text-glow">🚀 Adicionar Categoria Rápida</h5>
        <form method="post" action="{{ url_for('add_category') }}" class="row g-3 align-items-end">
          <div class="col-md-5">
            <label class="form-label">📝 Nome</label>
            <input name="new_category" class="form-control" placeholder="Nova categoria" required>
          </div>
          <div class="col-md-4">
            <label class="form-label">🎨 Ícone</label>
            <select name="icon_choice" class="form-select">
              <option value="📂">📂 Padrão</option>
              <option value="💡">💡 Luz</option>
              <option value="💧">💧 Água</option>
              <option value="🌐">🌐 Internet</option>
              <option value="🛒">🛒 Mercado</option>
              <option value="💳">💳 Cartão</option>
              <option value="🍔">🍔 Alimentação</option>
              <option value="🚗">🚗 Transporte</option>
              <option value="🎵">🎵 Streaming</option>
              <option value="🏥">🏥 Saúde</option>
              <option value="🎉">🎉 Lazer</option>
              <option value="💻">💻 Tecnologia</option>
              <option value="🧾">🧾 Outros</option>
            </select>
          </div>
          <div class="col-md-3">
            <button class="btn btn-modern w-100" type="submit">➕ Adicionar</button>
          </div>
        </form>
      </div>
    </div>
  </div>
</div>

<footer class="container text-center mt-4 pb-4">
  <div class="modern-card p-3">
    <p class="text-muted mb-0">🔒 Aplicação Local • Dados salvos em <code>dados.json</code></p>
  </div>
</footer>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.2/dist/js/bootstrap.bundle.min.js"></script>
<script>
  function toggleParcelas(cb){
    document.getElementById('parcelasBox').style.display = cb.checked ? 'block' : 'none';
  }

  function toggleRecorrenciaOptions(){
    const indefCb = document.getElementById('recorrente_indef');
    const monthsBox = document.getElementById('recorrenciaMonthsBox');
    if(indefCb.checked){
      monthsBox.style.display = 'none';
      monthsBox.querySelector('input').value = 0;
    } else {
      monthsBox.style.display = 'block';
    }
  }

  document.addEventListener('DOMContentLoaded', toggleRecorrenciaOptions);
</script>
</body>
</html>
"""

# Injeta a função decimal_to_brl nos templates
@app.context_processor
def inject_helpers():
    return dict(decimal_to_brl=decimal_to_brl)

# ---------- Execução ----------
if __name__ == "__main__":
    print("🚀 Iniciando Organizador de Contas Moderno em http://127.0.0.1:5000")
    print(f"📁 Dados salvos em: {DATA_FILE}")
    print("✨ Interface repaginada com tema moderno!")
    app.run(debug=True, host="127.0.0.1", port=5000)