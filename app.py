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
 - RESPONSIVO: Otimizado para PC e Mobile
 - OTIMIZADO: Layout mais compacto para reduzir rolagem
 - BOTÃO NOVA CONTA OTIMIZADO: Cor contrastante com o fundo do projeto
 - INTERFACE COMPACTA: Campos e espaçamentos reduzidos para melhor aproveitamento do espaço
 - CORREÇÃO: Campo "Valor Pago" adicionado na tela inicial
 - CORREÇÃO: Botão "Salvar" funcionando corretamente na edição
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
    # Remove R$ se presente
    v = v.replace("R$", "").strip()
    # Se tem ponto E vírgula, assume formato brasileiro (1.234,56)
    if "." in v and "," in v:
        v = v.replace(".", "").replace(",", ".")
    # Se tem apenas vírgula, assume formato brasileiro (1234,56)
    elif "," in v and "." not in v:
        v = v.replace(",", ".")
    # Se tem apenas ponto, assume formato americano (1234.56)
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
        # Normalização mais cuidadosa dos dados ao carregar
        amount_raw = data.get("amount_decimal") or data.get("valor") or data.get("value") or "0.00"
        
        # Se o valor já é um Decimal ou número, converter para string primeiro
        if isinstance(amount_raw, (Decimal, int, float)):
            amount_raw = str(amount_raw)
        
        amount = money_to_decimal(amount_raw)
        
        # Tratar paid_amount de forma mais cuidadosa
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
                print(f"Erro ao carregar conta: {c_data}. Ignorando. Erro: {e}")

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
        current_contas = self.contas.copy()
        current_contas.append(conta)
        self.contas = current_contas

    def update_conta(self, updated_conta: Conta):
        """Atualiza uma conta existente."""
        current_contas = self.contas.copy()
        for i, c in enumerate(current_contas):
            if c.id == updated_conta.id:
                current_contas[i] = updated_conta
                self.contas = current_contas
                return
        raise ValueError(f"Conta com ID {updated_conta.id} não encontrada para atualização.")

    def delete_conta(self, conta_id: str):
        """Exclui uma conta pelo ID."""
        current_contas = self.contas.copy()
        initial_count = len(current_contas)
        current_contas = [c for c in current_contas if c.id != conta_id]
        if len(current_contas) == initial_count:
            raise ValueError(f"Conta com ID {conta_id} não encontrada para exclusão.")
        self.contas = current_contas

    def add_category(self, category: Category):
        """Adiciona uma nova categoria, verificando duplicatas."""
        if any(c.name.lower() == category.name.lower() for c in self.categories):
            raise ValueError(f"Categoria '{category.name}' já existe.")
        current_categories = self.categories.copy()
        current_categories.append(category)
        self.categories = current_categories

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

                # Evitar duplicatas
                exists = any(
                    (c.month == month_key) and (
                        c.rec_origin == origin_id or
                        (not c.rec_origin and c.name == origin_conta.name and c.month == origin_conta.month and c.id != origin_id)
                    )
                    for c in self.contas
                )
                if exists:
                    continue

                if rec_type == "indef":
                    # Gera a próxima fatura com valor 0
                    inst_month = add_months(parse_month_input(origin_conta.month), 1)
                    if month_key_from_date(inst_month) == month_key:
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

                    for i in range(1, rec_months):
                        next_date = add_months(origin_date, i)
                        next_month_key = month_key_from_date(next_date)
                        if next_month_key == month_key:
                            # Pegar valor do mês anterior se existir, senão usa o valor da origem
                            prev_month_val = origin_conta.amount_decimal
                            prev_date_for_value = add_months(next_date, -1)
                            prev_month_key_for_value = month_key_from_date(prev_date_for_value)
                            
                            # Tentar encontrar a instância da conta para o mês anterior
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
            current_contas = self.contas.copy()
            current_contas.extend(contas_to_add)
            self.contas = current_contas

# Inicializa o DataManager
data_manager = DataManager(DATA_FILE)

# Garantir recorrências para o mês atual ao iniciar a aplicação
try:
    data_manager.ensure_recurring_for_month(date.today().strftime("%Y-%m"))
except Exception as e:
    print(f"Erro ao gerar recorrências iniciais: {e}")

# ---------- Template HTML ----------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Organizador de Contas</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 8px;
            font-size: 14px;
        }
        
        .container {
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 15px 30px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%);
            color: white;
            padding: 12px 20px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 1.5rem;
            margin-bottom: 3px;
            font-weight: 300;
        }
        
        .header p {
            font-size: 0.85rem;
            opacity: 0.9;
        }
        
        .content {
            padding: 12px;
        }
        
        .filters {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 8px;
            margin-bottom: 12px;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 8px;
        }
        
        .form-group {
            display: flex;
            flex-direction: column;
        }
        
        .form-group label {
            font-weight: 600;
            margin-bottom: 3px;
            color: #2c3e50;
            font-size: 0.75rem;
        }
        
        .form-group input, .form-group select {
            padding: 6px 8px;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            font-size: 13px;
            transition: all 0.2s ease;
        }
        
        .form-group input:focus, .form-group select:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.1);
        }
        
        .btn {
            padding: 6px 12px;
            border: none;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            text-decoration: none;
            display: inline-block;
            text-align: center;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .btn-primary:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 8px rgba(102, 126, 234, 0.3);
        }
        
        .btn-success {
            background: linear-gradient(135deg, #56ab2f 0%, #a8e6cf 100%);
            color: white;
        }
        
        .btn-danger {
            background: linear-gradient(135deg, #ff416c 0%, #ff4b2b 100%);
            color: white;
        }
        
        .btn-warning {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
        }
        
        .summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 10px;
            margin-bottom: 12px;
        }
        
        .summary-card {
            background: white;
            padding: 10px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
            border-left: 3px solid;
            transition: transform 0.2s ease;
        }
        
        .summary-card:hover {
            transform: translateY(-2px);
        }
        
        .summary-card.pending {
            border-left-color: #ff6b6b;
        }
        
        .summary-card.paid {
            border-left-color: #51cf66;
        }
        
        .summary-card.total {
            border-left-color: #339af0;
        }
        
        .summary-card.valor-pago {
            border-left-color: #28a745;
        }
        
        .summary-card h3 {
            font-size: 0.75rem;
            color: #666;
            margin-bottom: 4px;
        }
        
        .summary-card .value {
            font-size: 1.2rem;
            font-weight: bold;
            color: #2c3e50;
        }
        
        .accounts-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 10px;
        }
        
        .account-card {
            background: white;
            border-radius: 8px;
            padding: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.06);
            border-left: 3px solid;
            transition: all 0.2s ease;
            position: relative;
        }
        
        .account-card:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }
        
        .account-card.pending {
            border-left-color: #ff6b6b;
        }
        
        .account-card.paid {
            border-left-color: #51cf66;
        }
        
        .account-title {
            font-size: 0.95rem;
            font-weight: bold;
            color: #2c3e50;
            margin-bottom: 4px;
            line-height: 1.2;
            padding-right: 60px;
        }
        
        .account-category {
            display: inline-flex;
            align-items: center;
            padding: 2px 6px;
            border-radius: 10px;
            font-size: 0.65rem;
            font-weight: 600;
            color: white;
            margin-bottom: 6px;
        }
        
        .account-amount {
            font-size: 1.1rem;
            font-weight: bold;
            color: #2c3e50;
            margin-bottom: 6px;
        }
        
        .account-status {
            padding: 3px 8px;
            border-radius: 10px;
            font-size: 0.65rem;
            font-weight: 600;
            text-transform: uppercase;
            position: absolute;
            top: 8px;
            right: 8px;
        }
        
        .status-pending {
            background: #ffe0e0;
            color: #d63384;
        }
        
        .status-paid {
            background: #d4edda;
            color: #155724;
        }
        
        .account-actions {
            display: flex;
            gap: 4px;
            margin-top: 8px;
            flex-wrap: wrap;
        }
        
        .account-meta {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
            gap: 6px;
            margin-top: 8px;
            padding-top: 8px;
            border-top: 1px solid #eee;
        }
        
        .meta-item {
            display: flex;
            flex-direction: column;
        }
        
        .meta-label {
            font-size: 0.6rem;
            color: #666;
            text-transform: uppercase;
            font-weight: 600;
            margin-bottom: 2px;
        }
        
        .meta-value {
            font-size: 0.7rem;
            color: #2c3e50;
            font-weight: 500;
        }
        
        .flash-messages {
            margin-bottom: 10px;
        }
        
        .flash-message {
            padding: 8px 12px;
            border-radius: 6px;
            margin-bottom: 6px;
            font-weight: 500;
            font-size: 0.8rem;
        }
        
        .flash-success {
            background: #d4edda;
            color: #155724;
            border: 1px solid #c3e6cb;
        }
        
        .flash-error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        
        /* BOTÃO NOVA CONTA - Cor contrastante com o fundo roxo/azul */
        .add-account-btn {
            position: fixed;
            bottom: 20px;
            right: 20px;
            width: 56px;
            height: 56px;
            border-radius: 50%;
            background: linear-gradient(135deg, #ff6b35 0%, #f7931e 100%);
            color: white;
            border: none;
            font-size: 24px;
            font-weight: 300;
            cursor: pointer;
            box-shadow: 0 8px 20px rgba(255, 107, 53, 0.4);
            transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            z-index: 1000;
            display: flex;
            align-items: center;
            justify-content: center;
            text-decoration: none;
            overflow: hidden;
        }
        
        .add-account-btn::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: linear-gradient(135deg, #e74c3c 0%, #ff6b35 100%);
            opacity: 0;
            transition: opacity 0.3s ease;
            border-radius: 50%;
        }
        
        .add-account-btn:hover {
            transform: scale(1.1) translateY(-2px);
            box-shadow: 0 12px 30px rgba(255, 107, 53, 0.6);
        }
        
        .add-account-btn:hover::before {
            opacity: 1;
        }
        
        .add-account-btn:active {
            transform: scale(1.05) translateY(-1px);
        }
        
        .add-account-btn span {
            position: relative;
            z-index: 2;
        }
        
        /* Animação de pulso para chamar atenção */
        @keyframes pulse {
            0% {
                box-shadow: 0 8px 20px rgba(255, 107, 53, 0.4);
            }
            50% {
                box-shadow: 0 8px 20px rgba(255, 107, 53, 0.7);
            }
            100% {
                box-shadow: 0 8px 20px rgba(255, 107, 53, 0.4);
            }
        }
        
        .add-account-btn {
            animation: pulse 2s infinite;
        }
        
        .add-account-btn:hover {
            animation: none;
        }
        
        .notes {
            margin-top: 6px;
            color: #666;
            font-style: italic;
            font-size: 0.75rem;
            line-height: 1.3;
        }
        
        @media (max-width: 768px) {
            .container {
                margin: 5px;
                border-radius: 10px;
            }
            
            .content {
                padding: 10px;
            }
            
            .filters {
                grid-template-columns: 1fr;
                gap: 6px;
            }
            
            .summary {
                grid-template-columns: 1fr;
            }
            
            .accounts-grid {
                grid-template-columns: 1fr;
            }
            
            .account-status {
                position: static;
                margin-top: 6px;
            }
            
            .account-title {
                padding-right: 0;
            }
            
            .add-account-btn {
                bottom: 15px;
                right: 15px;
                width: 50px;
                height: 50px;
                font-size: 20px;
            }
        }
        
        @media (max-width: 480px) {
            .btn {
                padding: 4px 8px;
                font-size: 11px;
            }
            
            .account-card {
                padding: 8px;
            }
            
            .account-title {
                font-size: 0.85rem;
            }
            
            .account-amount {
                font-size: 1rem;
            }
            
            .add-account-btn {
                width: 45px;
                height: 45px;
                font-size: 18px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>💰 Organizador de Contas</h1>
            <p>Gerencie suas finanças de forma inteligente</p>
        </div>
        
        <div class="content">
            {% if get_flashed_messages() %}
                <div class="flash-messages">
                    {% for message in get_flashed_messages() %}
                        <div class="flash-message flash-success">{{ message }}</div>
                    {% endfor %}
                </div>
            {% endif %}
            
            <form method="GET" class="filters">
                <div class="form-group">
                    <label for="month">Mês</label>
                    <input type="month" id="month" name="month" value="{{ selected_month }}">
                </div>
                
                <div class="form-group">
                    <label for="category">Categoria</label>
                    <select id="category" name="category">
                        <option value="Todos" {% if selected_category == 'Todos' %}selected{% endif %}>Todas</option>
                        {% for cat in categories %}
                            <option value="{{ cat.name }}" {% if selected_category == cat.name %}selected{% endif %}>
                                {{ cat.icon }} {{ cat.name }}
                            </option>
                        {% endfor %}
                    </select>
                </div>
                
                <div class="form-group">
                    <label for="q">Buscar</label>
                    <input type="text" id="q" name="q" value="{{ search_query }}" placeholder="Nome da conta...">
                </div>
                
                <div class="form-group">
                    <label>&nbsp;</label>
                    <button type="submit" class="btn btn-primary">Filtrar</button>
                </div>
            </form>
            
            <div class="summary">
                <div class="summary-card pending">
                    <h3>Contas Pendentes</h3>
                    <div class="value">{{ summary.pending_count }}</div>
                </div>
                <div class="summary-card paid">
                    <h3>Contas Pagas</h3>
                    <div class="value">{{ summary.paid_count }}</div>
                </div>
                <div class="summary-card total">
                    <h3>Valor Total</h3>
                    <div class="value">{{ summary.total_amount }}</div>
                </div>
                <div class="summary-card valor-pago">
                    <h3>Valor Já Pago</h3>
                    <div class="value">{{ summary.valor_pago }}</div>
                </div>
            </div>
            
            <div class="accounts-grid">
                {% for conta in contas %}
                    <div class="account-card {{ conta.status }}">
                        <div class="account-status status-{{ conta.status }}">
                            {{ 'Paga' if conta.status == 'paid' else 'Pendente' }}
                        </div>
                        
                        <div class="account-title">{{ conta.name }}</div>
                        <div class="account-category" style="background-color: {{ conta.category_color }};">
                            {{ conta.category_icon }} {{ conta.category }}
                        </div>
                        
                        <div class="account-amount">{{ conta.amount_formatted }}</div>
                        
                        {% if conta.notes %}
                            <div class="notes">{{ conta.notes }}</div>
                        {% endif %}
                        
                        <div class="account-meta">
                            <div class="meta-item">
                                <div class="meta-label">Mês</div>
                                <div class="meta-value">{{ conta.month }}</div>
                            </div>
                            {% if conta.paid_at %}
                                <div class="meta-item">
                                    <div class="meta-label">Pago em</div>
                                    <div class="meta-value">{{ conta.paid_at.strftime('%d/%m/%Y') }}</div>
                                </div>
                            {% endif %}
                            {% if conta.paid_amount and conta.paid_amount != conta.amount_decimal %}
                                <div class="meta-item">
                                    <div class="meta-label">Valor Pago</div>
                                    <div class="meta-value">{{ decimal_to_brl(conta.paid_amount) }}</div>
                                </div>
                            {% endif %}
                            {% if conta.recorrente %}
                                <div class="meta-item">
                                    <div class="meta-label">Recorrência</div>
                                    <div class="meta-value">
                                        {% if conta.rec_type == 'indef' %}
                                            Indefinida
                                        {% elif conta.rec_type == 'fixed' %}
                                            {{ conta.recorrencia_months }} meses
                                        {% endif %}
                                    </div>
                                </div>
                            {% endif %}
                            {% if conta.parcelada %}
                                <div class="meta-item">
                                    <div class="meta-label">Parcela</div>
                                    <div class="meta-value">{{ conta.parcel_index }}/{{ conta.parcel_total }}</div>
                                </div>
                            {% endif %}
                        </div>
                        
                        <div class="account-actions">
                            <a href="{{ url_for('edit_conta', conta_id=conta.id) }}" class="btn btn-primary">Editar</a>
                            
                            {% if conta.status == 'pending' %}
                                <a href="{{ url_for('mark_paid', conta_id=conta.id) }}" class="btn btn-success">Pagar</a>
                            {% else %}
                                <a href="{{ url_for('mark_pending', conta_id=conta.id) }}" class="btn btn-warning">Desfazer</a>
                            {% endif %}
                            
                            <a href="{{ url_for('delete_conta', conta_id=conta.id) }}" 
                               class="btn btn-danger" 
                               onclick="return confirm('Tem certeza que deseja excluir esta conta?')">Excluir</a>
                        </div>
                    </div>
                {% endfor %}
            </div>
            
            {% if not contas %}
                <div style="text-align: center; padding: 30px; color: #666;">
                    <h3>Nenhuma conta encontrada</h3>
                    <p>Adicione uma nova conta para começar!</p>
                </div>
            {% endif %}
        </div>
    </div>
    
    <a href="{{ url_for('add_conta') }}" class="add-account-btn" title="Adicionar Nova Conta">
        <span>+</span>
    </a>
</body>
</html>
"""

FORM_TEMPLATE = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ title }} - Organizador de Contas</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 10px;
            font-size: 14px;
        }
        
        .container {
            max-width: 700px;
            margin: 0 auto;
            background: white;
            border-radius: 12px;
            box-shadow: 0 15px 30px rgba(0,0,0,0.1);
            overflow: hidden;
        }
        
        .header {
            background: linear-gradient(135deg, #2c3e50 0%, #34495e 100%);
            color: white;
            padding: 20px;
            text-align: center;
        }
        
        .header h1 {
            font-size: 1.5rem;
            margin-bottom: 6px;
            font-weight: 300;
        }
        
        .header p {
            font-size: 0.9rem;
            opacity: 0.9;
        }
        
        .content {
            padding: 20px;
        }
        
        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        
        .form-group {
            display: flex;
            flex-direction: column;
        }
        
        .form-group label {
            font-weight: 600;
            margin-bottom: 5px;
            color: #2c3e50;
            font-size: 0.85rem;
        }
        
        .form-group input, .form-group select, .form-group textarea {
            padding: 10px;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            font-size: 14px;
            transition: all 0.2s ease;
            font-family: inherit;
        }
        
        .form-group textarea {
            resize: vertical;
            min-height: 70px;
        }
        
        .form-group input:focus, .form-group select:focus, .form-group textarea:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.1);
        }
        
        .checkbox-group {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 8px;
        }
        
        .checkbox-group input[type="checkbox"] {
            width: auto;
            margin: 0;
        }
        
        .btn {
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            text-decoration: none;
            display: inline-block;
            text-align: center;
            margin-right: 10px;
            margin-bottom: 10px;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .btn-primary:hover {
            transform: translateY(-1px);
            box-shadow: 0 6px 12px rgba(102, 126, 234, 0.3);
        }
        
        .btn-secondary {
            background: #6c757d;
            color: white;
        }
        
        .btn-secondary:hover {
            background: #5a6268;
            transform: translateY(-1px);
        }
        
        .actions {
            display: flex;
            gap: 10px;
            margin-top: 20px;
            flex-wrap: wrap;
        }
        
        .flash-messages {
            margin-bottom: 15px;
        }
        
        .flash-message {
            padding: 10px 15px;
            border-radius: 6px;
            margin-bottom: 8px;
            font-weight: 500;
            font-size: 0.85rem;
        }
        
        .flash-error {
            background: #f8d7da;
            color: #721c24;
            border: 1px solid #f5c6cb;
        }
        
        .conditional-fields {
            display: none;
            grid-column: 1 / -1;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 6px;
            margin-top: 10px;
        }
        
        .conditional-fields.show {
            display: block;
        }
        
        .conditional-fields h4 {
            margin-bottom: 10px;
            font-size: 0.9rem;
        }
        
        @media (max-width: 768px) {
            .container {
                margin: 5px;
                border-radius: 10px;
            }
            
            .content {
                padding: 15px;
            }
            
            .form-grid {
                grid-template-columns: 1fr;
            }
            
            .actions {
                flex-direction: column;
            }
            
            .btn {
                margin-right: 0;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{{ title }}</h1>
            <p>{{ subtitle }}</p>
        </div>
        
        <div class="content">
            {% if get_flashed_messages() %}
                <div class="flash-messages">
                    {% for message in get_flashed_messages() %}
                        <div class="flash-message flash-error">{{ message }}</div>
                    {% endfor %}
                </div>
            {% endif %}
            
            <form method="POST">
                <div class="form-grid">
                    <div class="form-group">
                        <label for="name">Nome da Conta *</label>
                        <input type="text" id="name" name="name" value="{{ conta.name if conta else '' }}" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="amount">Valor *</label>
                        <input type="text" id="amount" name="amount" 
                               value="{{ decimal_to_brl(conta.amount_decimal) if conta else '' }}" 
                               placeholder="R$ 0,00" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="month">Mês *</label>
                        <input type="month" id="month" name="month" 
                               value="{{ conta.month if conta else selected_month }}" required>
                    </div>
                    
                    <div class="form-group">
                        <label for="category">Categoria</label>
                        <select id="category" name="category">
                            {% for cat in categories %}
                                <option value="{{ cat.name }}" 
                                        {% if (conta and conta.category == cat.name) or (not conta and cat.name == 'Outros') %}selected{% endif %}>
                                    {{ cat.icon }} {{ cat.name }}
                                </option>
                            {% endfor %}
                        </select>
                    </div>
                    
                    <div class="form-group" style="grid-column: 1 / -1;">
                        <label for="notes">Observações</label>
                        <textarea id="notes" name="notes" placeholder="Observações opcionais...">{{ conta.notes if conta else '' }}</textarea>
                    </div>
                    
                    {% if not conta or not conta.rec_origin %}
                        <div class="form-group">
                            <label>Opções Avançadas</label>
                            <div class="checkbox-group">
                                <input type="checkbox" id="recorrente" name="recorrente" 
                                       {% if conta and conta.recorrente %}checked{% endif %}
                                       onchange="toggleRecurrence()">
                                <label for="recorrente">Conta Recorrente</label>
                            </div>
                            <div class="checkbox-group">
                                <input type="checkbox" id="parcelada" name="parcelada" 
                                       {% if conta and conta.parcelada %}checked{% endif %}
                                       onchange="toggleInstallments()">
                                <label for="parcelada">Conta Parcelada</label>
                            </div>
                        </div>
                        
                        <div id="recurrence-fields" class="conditional-fields">
                            <h4>Configurações de Recorrência</h4>
                            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px;">
                                <div class="form-group">
                                    <label for="rec_type">Tipo de Recorrência</label>
                                    <select id="rec_type" name="rec_type">
                                        <option value="indef" {% if conta and conta.rec_type == 'indef' %}selected{% endif %}>
                                            Indefinida (valor variável)
                                        </option>
                                        <option value="fixed" {% if conta and conta.rec_type == 'fixed' %}selected{% endif %}>
                                            Fixa (valor fixo)
                                        </option>
                                    </select>
                                </div>
                                <div class="form-group">
                                    <label for="recorrencia_months">Duração (meses)</label>
                                    <input type="number" id="recorrencia_months" name="recorrencia_months" 
                                           value="{{ conta.recorrencia_months if conta else 12 }}" min="0" max="120">
                                    <small style="color: #666; margin-top: 3px; font-size: 0.75rem;">Deixe em branco para indefinido</small>
                                </div>
                            </div>
                        </div>
                        
                        <div id="installment-fields" class="conditional-fields">
                            <h4>Configurações de Parcelamento</h4>
                            <div class="form-group">
                                <label for="parcelas">Número de Parcelas</label>
                                <input type="number" id="parcelas" name="parcelas" 
                                       value="{{ conta.parcelas if conta else 2 }}" min="1" max="60">
                            </div>
                        </div>
                    {% endif %}
                </div>
                
                <div class="actions">
                    <button type="submit" class="btn btn-primary">
                        {{ 'Salvar' if conta else 'Adicionar Conta' }}
                    </button>
                    <a href="{{ url_for('index') }}" class="btn btn-secondary">Cancelar</a>
                </div>
            </form>
        </div>
    </div>
    
    <script>
        function toggleRecurrence() {
            const checkbox = document.getElementById('recorrente');
            const fields = document.getElementById('recurrence-fields');
            if (checkbox.checked) {
                fields.classList.add('show');
            } else {
                fields.classList.remove('show');
            }
        }
        
        function toggleInstallments() {
            const checkbox = document.getElementById('parcelada');
            const fields = document.getElementById('installment-fields');
            if (checkbox.checked) {
                fields.classList.add('show');
            } else {
                fields.classList.remove('show');
            }
        }
        
        // Inicializar campos condicionais
        document.addEventListener('DOMContentLoaded', function() {
            toggleRecurrence();
            toggleInstallments();
        });
        
        // Formatação de valor monetário
        document.getElementById('amount').addEventListener('input', function(e) {
            let value = e.target.value.replace(/\D/g, '');
            if (value.length > 0) {
                value = (parseInt(value) / 100).toFixed(2);
                value = value.replace('.', ',');
                value = value.replace(/\B(?=(\d{3})+(?!\d))/g, '.');
                e.target.value = 'R$ ' + value;
            }
        });
    </script>
</body>
</html>
"""

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
        flash(f"Erro ao gerar recorrências: {e}")

    # Filtrar contas
    contas = data_manager.contas
    filtered_contas = []
    
    for conta in contas:
        # Filtro por mês
        if conta.month != sel_month:
            continue
            
        # Filtro por categoria
        if sel_category_name != "Todos" and conta.category != sel_category_name:
            continue
            
        # Filtro por busca
        if q_search and q_search not in conta.name.lower():
            continue
            
        filtered_contas.append(conta)

    # Preparar dados para o template
    contas_data = []
    for conta in filtered_contas:
        # Encontrar categoria para obter ícone
        category_obj = next((c for c in data_manager.categories if c.name == conta.category), None)
        category_icon = category_obj.icon if category_obj else "📂"
        category_color = color_for_category(conta.category)
        
        contas_data.append({
            'id': conta.id,
            'name': conta.name,
            'amount_formatted': decimal_to_brl(conta.amount_decimal),
            'amount_decimal': conta.amount_decimal,
            'month': conta.month,
            'category': conta.category,
            'category_icon': category_icon,
            'category_color': category_color,
            'notes': conta.notes,
            'status': conta.status,
            'paid_at': conta.paid_at,
            'paid_amount': conta.paid_amount,
            'recorrente': conta.recorrente,
            'rec_type': conta.rec_type,
            'recorrencia_months': conta.recorrencia_months,
            'parcelada': conta.parcelada,
            'parcel_index': conta.parcel_index,
            'parcel_total': conta.parcel_total
        })

    # Calcular resumo
    pending_count = sum(1 for c in contas_data if c['status'] == 'pending')
    paid_count = sum(1 for c in contas_data if c['status'] == 'paid')
    total_amount = sum(c['amount_decimal'] for c in contas_data)
    
    # Calcular valor total já pago (todas as contas pagas do mês)
    valor_pago = sum(c['paid_amount'] or c['amount_decimal'] for c in contas_data if c['status'] == 'paid')

    summary = {
        'pending_count': pending_count,
        'paid_count': paid_count,
        'total_amount': decimal_to_brl(total_amount),
        'valor_pago': decimal_to_brl(valor_pago)
    }

    return render_template_string(HTML_TEMPLATE,
                                contas=contas_data,
                                categories=data_manager.categories,
                                selected_month=sel_month,
                                selected_category=sel_category_name,
                                search_query=request.args.get("q", ""),
                                summary=summary,
                                decimal_to_brl=decimal_to_brl)

@app.route("/add", methods=["GET", "POST"])
def add_conta():
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            amount_str = request.form.get("amount", "").strip()
            month = request.form.get("month", "").strip()
            category = request.form.get("category", "Outros").strip()
            notes = request.form.get("notes", "").strip()
            
            # Opções avançadas
            recorrente = bool(request.form.get("recorrente"))
            rec_type = request.form.get("rec_type") if recorrente else None
            recorrencia_months = int(request.form.get("recorrencia_months", 0) or 0) if recorrente else 0
            
            parcelada = bool(request.form.get("parcelada"))
            parcelas = int(request.form.get("parcelas", 1) or 1) if parcelada else 1

            if not name or not amount_str or not month:
                flash("Nome, valor e mês são obrigatórios!")
                return redirect(url_for("add_conta"))

            amount_decimal = money_to_decimal(amount_str)

            if parcelada and parcelas > 1:
                # Criar contas parceladas
                installment_amounts = split_amount_into_installments(amount_decimal, parcelas)
                base_month_date = parse_month_input(month)
                
                for i, installment_amount in enumerate(installment_amounts):
                    installment_month_date = add_months(base_month_date, i)
                    installment_month = month_key_from_date(installment_month_date)
                    
                    conta = Conta(
                        name=f"{name} ({i+1}/{parcelas})",
                        amount_decimal=installment_amount,
                        month=installment_month,
                        category=category,
                        notes=notes,
                        recorrente=recorrente,
                        rec_type=rec_type,
                        recorrencia_months=recorrencia_months,
                        parcelada=True,
                        parcelas=parcelas,
                        parcel_index=i+1,
                        parcel_total=parcelas
                    )
                    data_manager.add_conta(conta)
                
                flash(f"Conta parcelada adicionada com sucesso! ({parcelas} parcelas)")
            else:
                # Criar conta única
                conta = Conta(
                    name=name,
                    amount_decimal=amount_decimal,
                    month=month,
                    category=category,
                    notes=notes,
                    recorrente=recorrente,
                    rec_type=rec_type,
                    recorrencia_months=recorrencia_months,
                    parcelada=False,
                    parcelas=1
                )
                data_manager.add_conta(conta)
                flash("Conta adicionada com sucesso!")

            return redirect(url_for("index", month=month))

        except (ValueError, InvalidOperation) as e:
            flash(f"Erro ao adicionar conta: {e}")
            return redirect(url_for("add_conta"))

    # GET request
    selected_month = request.args.get("month", date.today().strftime("%Y-%m"))
    
    return render_template_string(FORM_TEMPLATE,
                                title="Adicionar Conta",
                                subtitle="Preencha os dados da nova conta",
                                categories=data_manager.categories,
                                selected_month=selected_month,
                                decimal_to_brl=decimal_to_brl)

@app.route("/edit/<conta_id>", methods=["GET", "POST"])
def edit_conta(conta_id):
    conta = data_manager.get_conta_by_id(conta_id)
    if not conta:
        flash("Conta não encontrada!")
        return redirect(url_for("index"))

    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            amount_str = request.form.get("amount", "").strip()
            month = request.form.get("month", "").strip()
            category = request.form.get("category", "Outros").strip()
            notes = request.form.get("notes", "").strip()

            if not name or not amount_str or not month:
                flash("Nome, valor e mês são obrigatórios!")
                return redirect(url_for("edit_conta", conta_id=conta_id))

            amount_decimal = money_to_decimal(amount_str)

            # Atualizar conta
            conta.name = name
            conta.amount_decimal = amount_decimal
            conta.month = month
            conta.category = category
            conta.notes = notes

            data_manager.update_conta(conta)
            flash("Conta atualizada com sucesso!")
            return redirect(url_for("index", month=month))

        except (ValueError, InvalidOperation) as e:
            flash(f"Erro ao atualizar conta: {e}")
            return redirect(url_for("edit_conta", conta_id=conta_id))

    # GET request
    return render_template_string(FORM_TEMPLATE,
                                title="Editar Conta",
                                subtitle="Altere os dados da conta",
                                conta=conta,
                                categories=data_manager.categories,
                                decimal_to_brl=decimal_to_brl)

@app.route("/pay/<conta_id>")
def mark_paid(conta_id):
    conta = data_manager.get_conta_by_id(conta_id)
    if not conta:
        flash("Conta não encontrada!")
        return redirect(url_for("index"))

    conta.status = "paid"
    conta.paid_at = datetime.now()
    conta.paid_amount = conta.amount_decimal
    
    data_manager.update_conta(conta)
    flash("Conta marcada como paga!")
    return redirect(url_for("index", month=conta.month))

@app.route("/unpay/<conta_id>")
def mark_pending(conta_id):
    conta = data_manager.get_conta_by_id(conta_id)
    if not conta:
        flash("Conta não encontrada!")
        return redirect(url_for("index"))

    conta.status = "pending"
    conta.paid_at = None
    conta.paid_amount = None
    
    data_manager.update_conta(conta)
    flash("Pagamento desfeito!")
    return redirect(url_for("index", month=conta.month))

@app.route("/delete/<conta_id>")
def delete_conta(conta_id):
    conta = data_manager.get_conta_by_id(conta_id)
    if not conta:
        flash("Conta não encontrada!")
        return redirect(url_for("index"))

    month = conta.month
    data_manager.delete_conta(conta_id)
    flash("Conta excluída com sucesso!")
    return redirect(url_for("index", month=month))

@app.route("/api/summary")
def api_summary():
    """API endpoint para obter resumo das contas"""
    try:
        contas = data_manager.contas
        total_contas = len(contas)
        contas_pagas = sum(1 for c in contas if c.status == "paid")
        contas_pendentes = total_contas - contas_pagas
        valor_total = sum(c.amount_decimal for c in contas)
        valor_pago = sum(c.paid_amount or c.amount_decimal for c in contas if c.status == "paid")
        valor_pendente = valor_total - valor_pago

        return jsonify({
            "success": True,
            "data": {
                "total_contas": total_contas,
                "contas_pagas": contas_pagas,
                "contas_pendentes": contas_pendentes,
                "valor_total": float(valor_total),
                "valor_pago": float(valor_pago),
                "valor_pendente": float(valor_pendente)
            }
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)