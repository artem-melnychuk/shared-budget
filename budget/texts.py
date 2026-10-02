"""Everything the bot says, in Russian. Messages use Telegram's HTML parse mode."""

from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

from budget.balance import Balance, SplitRule
from budget.categories import KEYWORDS, UNCATEGORIZED, category_of
from budget.members import Members
from budget.report import MonthReport
from budget.storage import Expense

CATEGORY_LABELS = {
    "groceries": "Продукты",
    "bakery": "Булочная",
    "eating out": "Кафе и рестораны",
    "transport": "Транспорт",
    "home": "Дом и счета",
    "health": "Здоровье",
    "subscriptions": "Подписки и связь",
    "leisure": "Досуг",
    "clothes": "Одежда",
    UNCATEGORIZED: "Прочее",
}
CATEGORIES = [*KEYWORDS, UNCATEGORIZED]

MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь", "июль",
          "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]

KIND_LABELS = {"photo": "фото", "document": "документ", "text": "текст", "manual": "вручную"}

# --- buttons -------------------------------------------------------------

BTN_PAYER = "👤 Платит: {name}"
BTN_SHARED = "👥 Общая → сделать личной"
BTN_PERSONAL = "🙋 Личная → сделать общей"
BTN_CATEGORY = "🗂 Категория"
BTN_REIMBURSEMENT = "↩️ Это возврат долга"
BTN_NOT_REIMBURSEMENT = "🧾 Это не возврат, а трата"
BTN_DELETE = "🗑 Удалить"
BTN_DELETE_YES = "Да, удалить"
BTN_BACK = "← Назад"
BTN_CHOSEN = "✓ {label}"
BTN_OPEN = "#{id} · {amount}"

# --- short answers to button presses (toasts) ----------------------------

TOAST_NOT_FOUND = "Трата не найдена: возможно, её удалили."
TOAST_SAVED = "Сохранено"
TOAST_DELETED = "Удалено"
TOAST_NOT_ALLOWED = "Этот бот только для участников бюджета."

# --- messages -------------------------------------------------------------

HELP = (
    "Я веду общий бюджет.\n\n"
    "• Пересылайте мне чеки (фото, PDF, скриншоты) и сообщения вида "
    "<code>12.50 boulangerie</code>; можно сразу пачкой.\n"
    "• На каждую трату я покажу карточку: там можно сменить плательщика, "
    "сделать трату общей или личной, выбрать категорию, отметить возврат долга или удалить.\n"
    "• Если у чека нет суммы, ответьте на его карточку суммой, например <code>23,90</code>.\n"
    "• Вернули долг — напишите <code>вернул 32</code> или <code>remboursé 32</code>: "
    "это запишется как возврат от вас второму участнику.\n\n"
    "/balance — кто кому должен\n"
    "/report — отчёт за текущий месяц, /report 2026-10 — за указанный"
)
NOT_AN_EXPENSE = "Не нашёл здесь суммы. Пример траты: <code>12.50 boulangerie</code>. /help — что я умею."
AMOUNT_SAVED = "✅ Сумма {amount} сохранена для #{id}."
NOT_AN_AMOUNT = "Не понял сумму. Ответьте на карточку числом, например <code>23,90</code>."
BAD_MONTH = "Месяц пишется так: <code>/report 2026-10</code>."
DELETED = "🗑 Трата #{id} удалена."
DELETE_CONFIRM = "\n\n<b>Удалить эту трату?</b>"
CHOOSE_PAYER = "\n\n<b>Кто платил?</b>"
CHOOSE_CATEGORY = "\n\n<b>Выберите категорию:</b>"
CHOOSE_RECEIVER = "\n\n<b>Кому вернули деньги?</b>"
ALREADY_SAVED = "Эта трата уже записана."


def money(cents: int | None, currency: str = "EUR") -> str:
    if cents is None:
        return "без суммы"
    sign = "−" if cents < 0 else ""
    cents = abs(cents)
    symbol = "€" if currency == "EUR" else currency
    return f"{sign}{cents // 100},{cents % 100:02d} {symbol}"


def local_date(iso_utc: str, tz_name: str) -> str:
    return datetime.fromisoformat(iso_utc).astimezone(ZoneInfo(tz_name)).strftime("%d.%m.%Y")


def month_name(month: date) -> str:
    return f"{MONTHS[month.month - 1]} {month.year}"


def category_label(key: str) -> str:
    return CATEGORY_LABELS.get(key, key)


def split_label(rule: SplitRule) -> str:
    """Weights as percentages when they come out whole: 1/1 -> 50/50."""
    total = sum(rule.weights.values())
    if all(w * 100 % total == 0 for w in rule.weights.values()):
        return "/".join(str(w * 100 // total) for w in rule.weights.values())
    return rule.describe()


def card(e: Expense, members: Members, tz_name: str, duplicate: bool = False) -> str:
    lines = [ALREADY_SAVED, ""] if duplicate else []
    when = local_date(e.original_date, tz_name)
    if e.is_reimbursement:
        lines += [
            f"↩️ <b>Возврат долга #{e.id}</b>",
            f"Сумма: <b>{money(e.amount_cents, e.currency)}</b>",
            f"Дата: {when}",
            f"От кого: {escape(members.display(e.payer))}",
            f"Кому: {escape(members.display(e.paid_to))}",
        ]
    else:
        category = category_of(e)
        guessed = "" if e.category else " (по описанию)"
        lines += [
            f"🧾 <b>Трата #{e.id}</b>",
            f"Сумма: <b>{money(e.amount_cents, e.currency)}</b>",
            f"Дата: {when}",
            f"Платит: {escape(members.display(e.payer))}" + ("" if e.payer_confirmed else " (по умолчанию)"),
            f"Тип: {'общая' if e.is_shared else 'личная'}",
            f"Категория: {category_label(category)}{guessed}",
        ]
    if e.description:
        lines.append(f"Описание: {escape(e.description)}")
    lines.append(f"Источник: {KIND_LABELS.get(e.kind, e.kind)}")
    if e.amount_cents is None:
        lines += ["", "✍️ Ответьте на это сообщение суммой, например <code>23,90</code>."]
    else:
        lines += ["", "<i>Чтобы исправить сумму, ответьте на это сообщение.</i>"]
    return "\n".join(lines)


def deleted(expense_id: int) -> str:
    return DELETED.format(id=expense_id)


def summary_line(e: Expense, members: Members, tz_name: str) -> str:
    when = local_date(e.original_date, tz_name)[:5]
    if e.is_reimbursement:
        what = f"возврат {escape(members.display(e.payer))} → {escape(members.display(e.paid_to))}"
    else:
        what = f"{escape(members.display(e.payer))}, {'общая' if e.is_shared else 'личная'}"
        if e.description:
            what += f", {escape(e.description)}"
    return f"#{e.id} · {when} · {money(e.amount_cents, e.currency)} · {what}"


SKIP_REASONS = {
    "text is not an amount": "текст без суммы",
    "no photo, receipt document or text": "не чек и не текст",
    "sender is not a member": "отправитель не участник",
}


def batch_summary(received: int, added: list[Expense], duplicates: list[Expense],
                  skipped: dict[str, int], members: Members, tz_name: str, limit: int) -> str:
    lines = [f"📥 Получено сообщений: {received}."]
    if added:
        lines += ["", f"<b>Добавлено: {len(added)}</b>"]
        lines += [summary_line(e, members, tz_name) for e in added[:limit]]
        if len(added) > limit:
            lines.append(f"…и ещё {len(added) - limit}")
    if duplicates:
        lines += ["", f"<b>Уже были записаны: {len(duplicates)}</b>"]
        lines += [summary_line(e, members, tz_name) for e in duplicates[:limit]]
    if skipped:
        reasons = ", ".join(f"{SKIP_REASONS.get(r, r)}: {n}" for r, n in skipped.items())
        lines += ["", f"Пропущено: {sum(skipped.values())} ({reasons})"]
    without_amount = sum(1 for e in added if e.amount_cents is None)
    if added or duplicates:
        lines += ["", "Нажмите на трату, чтобы открыть её карточку."]
    if without_amount:
        lines.append(f"Без суммы: {without_amount}. Сумму пришлите ответом на карточку.")
    return "\n".join(lines)


def _debts(balance: Balance, members: Members) -> list[str]:
    if not balance.debts:
        return ["Все в расчёте 🤝"]
    return [f"Долг: <b>{escape(members.display(d.debtor))}</b> → <b>{escape(members.display(d.creditor))}</b>, "
            f"{money(d.amount_cents, balance.currency)}"
            for d in balance.debts]


def _not_counted(balance: Balance) -> list[str]:
    parts = []
    if balance.without_amount:
        parts.append(f"без суммы: {len(balance.without_amount)}")
    if balance.without_payer:
        parts.append(f"без плательщика: {len(balance.without_payer)}")
    if balance.other_currency:
        parts.append(f"в другой валюте: {len(balance.other_currency)}")
    return [f"Не учтено — {', '.join(parts)}."] if parts else []


def balance_message(balance: Balance, members: Members) -> str:
    lines = [f"💶 <b>Баланс за всё время</b> (деление {split_label(balance.rule)})", ""]
    lines += _debts(balance, members)
    lines += ["", f"Общих трат: {money(balance.shared_total, balance.currency)}"]
    for key, t in balance.members.items():
        lines.append(f"{escape(members.display(key))}: оплачено общих {money(t.paid_shared, balance.currency)}, "
                     f"доля {money(t.share, balance.currency)}")
    not_counted = _not_counted(balance)
    if not_counted:
        lines += ["", *not_counted]
    return "\n".join(lines)


def report_message(report: MonthReport, members: Members) -> str:
    b = report.month_balance
    cur = b.currency
    m = lambda c: money(c, cur)  # noqa: E731
    lines = [
        f"📊 <b>Отчёт: {month_name(report.month)}</b> (деление {split_label(report.rule)})",
        "",
        f"Учтено трат: {len(b.counted)} на {m(b.shared_total + b.personal_total)} "
        f"(общие {m(b.shared_total)}, личные {m(b.personal_total)})",
        *_not_counted(b),
        "",
        "<b>По участникам</b>",
    ]
    for key, t in b.members.items():
        name = escape(members.display(key))
        lines.append(f"👤 {name}: оплачено {m(t.paid)} (общее {m(t.paid_shared)}, личное {m(t.paid_personal)}); "
                     f"доля в общих {m(t.share)}; расходы {m(t.spent)}")
    lines += ["", "<b>По категориям</b>"]
    if report.categories:
        for key, line in report.categories.items():
            per_member = " · ".join(f"{escape(members.display(k))} {m(line.spent_by[k])}" for k in report.rule.members)
            lines.append(f"{category_label(key)} — {m(line.total)} ({per_member})")
    else:
        lines.append("В этом месяце трат нет.")
    if b.reimbursements:
        lines += ["", "<b>Возвраты долга</b>"]
        for e in b.reimbursements:
            lines.append(f"{local_date(e.original_date, report.tz_name)} "
                         f"{escape(members.display(e.payer))} → {escape(members.display(e.paid_to))} "
                         f"{m(e.amount_cents)}")
    lines += ["", "<b>Кто кому должен за месяц</b>", *_debts(b, members)]
    lines += ["", "<b>Итого на конец месяца</b>", *_debts(report.running_balance, members)]
    return "\n".join(lines)
