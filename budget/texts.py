"""Everything the bot says, in Russian. Messages use Telegram's HTML parse mode."""

from datetime import date, datetime
from html import escape
from zoneinfo import ZoneInfo

from budget.balance import Balance, SplitRule
from budget.categories import KEYWORDS, UNCATEGORIZED, category_of
from budget.members import Members
from budget import savings as savings_rules
from budget.report import MonthReport
from budget.savings import Savings
from budget.storage import Expense, Item

CATEGORY_LABELS = {
    "delivery": "Доставка",
    "groceries": "Продукты",
    "bakery": "Булочная",
    "eating out": "Кафе и рестораны",
    "transport": "Транспорт",
    "home": "Дом и счета",
    "health": "Здоровье",
    "subscriptions": "Подписки и связь",
    "leisure": "Досуг",
    "electronics": "Техника",
    "clothes": "Одежда",
    "beauty": "Красота и уход",
    "pets": "Животные",
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
BTN_REIMBURSEMENT = "↩️ Это перевод, а не трата"
BTN_NOT_REIMBURSEMENT = "🧾 Это трата, а не перевод"
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
    "сделать трату общей или личной, выбрать категорию, отметить перевод или удалить.\n"
    "• Если у чека нет суммы, пришлите её следующим сообщением, например <code>23,90</code>.\n"
    "• Дату пишите в конце: <code>12.50 boulangerie 01.10</code>, <code>5 café вчера</code>. "
    "Без даты трата записывается днём сообщения.\n"
    "• Перевели деньги друг другу — напишите <code>вернул 32</code> или <code>remboursé 32</code>: "
    "это запишется как перевод от вас второму участнику и не попадёт в траты.\n\n"
    "/balance — кто сколько потратил в этом месяце\n"
    "/report — отчёт за текущий месяц, /report 2026-10 — за указанный, "
    "/report 2026-08 2026-10 — за несколько месяцев"
)
NOT_AN_EXPENSE = "Не нашёл здесь суммы. Пример траты: <code>12.50 boulangerie</code>. /help — что я умею."
AMOUNT_SAVED = "✅ Сумма {amount} сохранена для #{id}."
DATE_SAVED = "✅ Дата {date} сохранена для #{id}."
AMOUNT_AND_DATE_SAVED = "✅ Сумма {amount} и дата {date} сохранены для #{id}."
NOT_AN_AMOUNT = ("Не понял. Ответьте на карточку суммой (<code>23,90</code>), суммой с датой "
                 "(<code>23,90 01.10</code>) или только датой (<code>01/10</code>, <code>вчера</code>).")
BAD_MONTH = ("Месяц пишется так: <code>/report 2026-10</code>, "
             "несколько месяцев: <code>/report 2026-08 2026-10</code>.")
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


def period_name(report: MonthReport) -> str:
    """`октябрь 2026`, `август – октябрь 2026`, `декабрь 2025 – февраль 2026`."""
    first, last = report.month, report.last_month or report.month
    if first == last:
        return month_name(first)
    if first.year == last.year:
        return f"{MONTHS[first.month - 1]} – {month_name(last)}"
    return f"{month_name(first)} – {month_name(last)}"


def category_label(key: str) -> str:
    return CATEGORY_LABELS.get(key, key)


def split_label(rule: SplitRule) -> str:
    """Weights as percentages when they come out whole: 1/1 -> 50/50."""
    total = sum(rule.weights.values())
    if all(w * 100 % total == 0 for w in rule.weights.values()):
        return "/".join(str(w * 100 // total) for w in rule.weights.values())
    return rule.describe()


def card(e: Expense, members: Members, tz_name: str, duplicate: bool = False,
         items: list[Item] | None = None, reading: bool = False) -> str:
    """`items`: lines read off the receipt; `reading`: the bot reads receipts by itself."""
    lines = [ALREADY_SAVED, ""] if duplicate else []
    when = local_date(e.original_date, tz_name)
    if e.is_reimbursement:
        lines += [
            f"↩️ <b>Перевод #{e.id}</b>",
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
    if items:
        lines.append(f"Товаров на чеке: {len(items)}")
    if e.card_last4:
        lines.append(f"Карта: •••• {escape(e.card_last4)}")
    if e.amount_cents is None and e.recognition == "pending" and reading:
        lines += ["", "⏳ Читаю чек, сумма появится сама. Можно не ждать и прислать её следующим "
                      "сообщением, например <code>23,90</code>."]
    elif e.amount_cents is None and e.recognition == "failed":
        lines += ["", "⚠️ Не получилось прочитать чек. Пришлите сумму следующим сообщением, "
                      "например <code>23,90</code>. Можно с датой: <code>23,90 01.10</code>."]
    elif e.amount_cents is None:
        lines += ["", "✍️ Пришлите сумму следующим сообщением, например <code>23,90</code>. "
                      "Можно с датой: <code>23,90 01.10</code>."]
    else:
        lines += ["", "<i>Чтобы исправить сумму или дату, ответьте на эту карточку: "
                      "<code>23,90</code>, <code>23,90 01.10</code> или <code>01/10</code>.</i>"]
    return "\n".join(lines)


def deleted(expense_id: int) -> str:
    return DELETED.format(id=expense_id)


ITEMS_SHOWN = 25


def recognized(outcome, items: list[Item], members: Members, tz_name: str) -> str:
    """What was read off a receipt: shop, date, total, the lines, and anything to check."""
    e, r = outcome.expense, outcome.receipt
    facts = [escape(e.description) if e.description else None, local_date(e.original_date, tz_name),
             money(r.total_cents, r.currency)]
    lines = [f"🧾 <b>Прочитал чек #{e.id}</b>: " + ", ".join(f for f in facts if f) + "."]
    if items:
        lines.append("")
        lines += [f"• {escape(i.name)} — {money(i.amount_cents, r.currency)}" for i in items[:ITEMS_SHOWN]]
        if len(items) > ITEMS_SHOWN:
            lines.append(f"…и ещё {len(items) - ITEMS_SHOWN}")
        if not r.items_match:
            lines += ["", f"⚠️ Товары в сумме дают {money(r.items_total, r.currency)}, а итог на чеке "
                          f"{money(r.total_cents, r.currency)}: что-то прочитано неточно."]
    if outcome.total_differs:
        lines += ["", f"На чеке {money(r.total_cents, r.currency)}, а у вас записано "
                      f"{money(e.amount_cents, e.currency)}. Оставил вашу сумму. Чтобы взять сумму с чека, "
                      f"ответьте на карточку: <code>{_plain(r.total_cents)}</code>."]
    return "\n".join(lines)


def recognition_failed(e: Expense) -> str:
    if e.amount_cents is not None:
        return f"⚠️ Не получилось прочитать чек #{e.id}. Сумма осталась та, что вы прислали."
    return (f"⚠️ Не получилось прочитать чек #{e.id}. Пришлите сумму следующим сообщением, "
            "например <code>23,90</code>.")


def summary_line(e: Expense, members: Members, tz_name: str) -> str:
    when = local_date(e.original_date, tz_name)[:5]
    if e.is_reimbursement:
        what = f"перевод {escape(members.display(e.payer))} → {escape(members.display(e.paid_to))}"
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


def _plain(cents: int) -> str:
    """An amount without the currency sign, for table cells: 15,62."""
    sign = "−" if cents < 0 else ""
    cents = abs(cents)
    return f"{sign}{cents // 100},{cents % 100:02d}"


def _table(corner: str, names: list[str], rows: list[tuple[str, list[int]]],
           totals: list[tuple[str, list[int]]]) -> str:
    """A monospace table: a column per member, body rows, a rule, total rows."""
    label_width = max(len(corner), *(len(label) for label, _ in rows + totals))
    widths = [max(len(name), *(len(_plain(values[i])) for _, values in rows + totals))
              for i, name in enumerate(names)]

    def row(label: str, cells: list[str]) -> str:
        return "  ".join([label.ljust(label_width), *(c.rjust(w) for c, w in zip(cells, widths))])

    lines = [row(corner, names)]
    lines += [row(label, [_plain(v) for v in values]) for label, values in rows]
    lines.append("-" * len(lines[0]))
    lines += [row(label, [_plain(v) for v in values]) for label, values in totals]
    return f"<pre>{escape(chr(10).join(lines))}</pre>"


def _symbol(currency: str) -> str:
    return "€" if currency == "EUR" else currency


def spending_table(report: MonthReport, members: Members) -> list[str]:
    """Who paid how much: a row per category, a column per member, monospace so it lines up."""
    b = report.month_balance
    if not b.counted:
        return ["За этот период трат нет." if report.is_range else "В этом месяце трат нет."]
    keys = list(report.rule.members)
    rows = [(category_label(c), [line.paid_by[k] for k in keys]) for c, line in report.categories.items()]
    totals = [
        ("Итого", [b.members[k].paid for k in keys]),
        ("  общие", [b.members[k].paid_shared for k in keys]),
        ("  личные", [b.members[k].paid_personal for k in keys]),
    ]
    return [_table(_symbol(b.currency), [members.display(k) for k in keys], rows, totals)]


def month_table(report: MonthReport, members: Members) -> list[str]:
    """For a range: who paid how much in each month, empty months included."""
    b = report.month_balance
    keys = list(report.rule.members)
    rows = [(month_name(m), [report.paid_by_month.get(m, {}).get(k, 0) for k in keys]) for m in report.months]
    totals = [("Итого", [b.members[k].paid for k in keys])]
    return [_table(_symbol(b.currency), [members.display(k) for k in keys], rows, totals)]


def _ids(expenses: list[Expense], limit: int = 10) -> str:
    shown = ", ".join(f"#{e.id}" for e in expenses[:limit])
    return shown + (f" и ещё {len(expenses) - limit}" if len(expenses) > limit else "")


def not_counted_expenses(balance: Balance) -> list[Expense]:
    """What the table leaves out and someone should fix; the bot adds a button for each."""
    return balance.without_amount + balance.without_payer + balance.other_currency


def _not_counted(balance: Balance) -> list[str]:
    lines = []
    if balance.without_amount:
        lines.append(f"⚠️ Не попали в таблицу, нет суммы: {_ids(balance.without_amount)}. "
                     "Откройте карточку и ответьте на неё суммой.")
    if balance.without_payer:
        lines.append(f"⚠️ Не попали в таблицу, не выбран плательщик: {_ids(balance.without_payer)}. "
                     "Откройте карточку и выберите, кто платил.")
    if balance.other_currency:
        lines.append(f"⚠️ Не попали в таблицу, другая валюта: {_ids(balance.other_currency)}.")
    return lines


def balance_message(report: MonthReport, members: Members) -> str:
    """/balance: the month's spending table, nothing else."""
    lines = [f"💶 <b>Кто сколько потратил: {month_name(report.month)}</b>", ""]
    lines += spending_table(report, members)
    not_counted = _not_counted(report.month_balance)
    if not_counted:
        lines += ["", *not_counted]
    return "\n".join(lines)


def report_message(report: MonthReport, members: Members) -> str:
    b = report.month_balance
    cur = b.currency
    m = lambda c: money(c, cur)  # noqa: E731
    lines = [
        f"📊 <b>Отчёт: {period_name(report)}</b>",
        "",
        f"Учтено трат: {len(b.counted)} на {m(b.shared_total + b.personal_total)} "
        f"(общие {m(b.shared_total)}, личные {m(b.personal_total)})",
        *_not_counted(b),
        "",
        "<b>Кто сколько потратил</b>",
        *spending_table(report, members),
    ]
    if report.is_range and b.counted:
        lines += ["", "<b>По месяцам</b>", *month_table(report, members)]
    if b.reimbursements:
        lines += ["", "<b>Переводы друг другу</b>"]
        for e in b.reimbursements:
            lines.append(f"{local_date(e.original_date, report.tz_name)} "
                         f"{escape(members.display(e.payer))} → {escape(members.display(e.paid_to))} "
                         f"{m(e.amount_cents)}")
    if not report.is_range:  # the savings block compares one month with the month before
        lines += ["", "<b>Где можно сэкономить</b>", *savings_lines(report.savings, cur)]
    return "\n".join(lines)


def _percent(share: float) -> str:
    return f"{share * 100:.0f}%"


def savings_lines(s: Savings | None, currency: str = "EUR") -> list[str]:
    if s is None or s.empty:
        return ["Ничего не бросается в глаза."]
    m = lambda c: money(c, currency)  # noqa: E731
    lines = []
    if s.recurring:
        lines.append(f"🔁 Регулярные платежи (та же сумма тому же продавцу {savings_rules.RECURRING_MONTHS} "
                     f"мес. подряд) — проверьте, все ли нужны:")
        lines += [f"• {escape(r.seller)}: {m(r.amount_cents)} в месяц, {m(r.yearly_cents)} в год"
                  for r in s.recurring]
    if s.small:
        lines.append(f"🪙 Частые мелкие траты (от {savings_rules.SMALL_MIN_COUNT} раз до "
                     f"{m(savings_rules.SMALL_LIMIT_CENTS)}):")
        lines += [f"• {category_label(x.category)}: {x.count} раз, всего {m(x.total_cents)}" for x in s.small]
    e = s.eating
    if e and e.eating_cents:
        parts = ", ".join(f"{category_label(c).lower()} {m(v)}" for c, v in e.by_category.items() if v)
        line = f"🍽 Доставка и рестораны: {m(e.eating_cents)} ({parts}) — {_percent(e.share)} всех трат"
        if e.previous_share is not None:
            line += f"; в прошлом месяце {_percent(e.previous_share)}"
        lines.append(line)
    return lines
