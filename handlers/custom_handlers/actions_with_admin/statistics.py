"""Модуль статистики для админа."""
import datetime

from aiogram import types
from aiogram.types import BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from database.transactions import payments_daily_breakdown, payments_summary_for_range
from keyboards.inline.back_admin_menu import back_admin_menu_button
from states.states import AdminStatsState
from utils.misc.reporting import build_weekly_report_chart


def _stats_menu_kb() -> types.InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="День", callback_data="stats_day")
    kb.button(text="Неделя", callback_data="stats_week")
    kb.button(text="Месяц", callback_data="stats_month")
    kb.button(text="Админ меню", callback_data="admin_menu")
    kb.adjust(1)
    return kb.as_markup()


async def stats_menu(callback: types.CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer("Выберите период:", reply_markup=_stats_menu_kb())


async def stats_day_start(callback: types.CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.answer("Введите дату (ГГГГ-ММ-ДД).")
    await state.set_state(AdminStatsState.day)



async def stats_week_start(callback: types.CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await callback.message.answer("Введите дату (ГГГГ-ММ-ДД), неделя будет рассчитана по ней.")
    await state.set_state(AdminStatsState.week)


async def stats_month_start(callback: types.CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AdminStatsState.month)
    await callback.answer()
    await callback.message.answer("Введите номер месяца (1-12).")


async def stats_day_selected(message: types.Message, state: FSMContext) -> None:
    date_str = (message.text or "").strip()
    try:
        target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        await message.answer("Не удалось распознать дату. Используйте ГГГГ-ММ-ДД.")
        return

    summary = await payments_summary_for_range(target_date, target_date)
    unpaid_total = summary["billed_total"] - summary["earned_total"]
    report_text = (
        f"Статистика за {target_date.isoformat()}:\n"
        f"Занятий проведено: {summary['lessons_total']}\n"
        f"Оплачено: {summary['lessons_paid']}\n"
        f"Заработано: {summary['earned_total']} ₽\n"
        f"К оплате: {unpaid_total} ₽"
    )
    await state.clear()
    await message.answer(report_text, reply_markup=back_admin_menu_button())


async def stats_week_selected(message: types.Message, state: FSMContext) -> None:
    date_str = (message.text or "").strip()
    try:
        target_date = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        await message.answer("Не удалось распознать дату. Используйте ГГГГ-ММ-ДД.")
        return

    week_start = target_date - datetime.timedelta(days=target_date.weekday())
    week_end = week_start + datetime.timedelta(days=6)
    summary = await payments_summary_for_range(week_start, week_end)
    daily = await payments_daily_breakdown(week_start, week_end)
    daily_map = {row[0]: row for row in daily}
    dates = [week_start + datetime.timedelta(days=i) for i in range(7)]
    amounts = [daily_map.get(d, (d, 0, 0, 0, 0))[2] for d in dates]

    unpaid_total = summary["billed_total"] - summary["earned_total"]
    report_text = (
        f"Статистика за неделю {week_start.isoformat()}–{week_end.isoformat()}:\n"
        f"Занятий проведено: {summary['lessons_total']}\n"
        f"Оплачено: {summary['lessons_paid']}\n"
        f"Заработано: {summary['earned_total']} ₽\n"
        f"К оплате: {unpaid_total} ₽"
    )

    chart_title = f"Week {week_start.isoformat()}..{week_end.isoformat()}"
    chart_buf = build_weekly_report_chart(dates, amounts, title=chart_title)
    chart_file = BufferedInputFile(chart_buf.getvalue(), filename="weekly.png")
    await state.clear()
    await message.answer_photo(chart_file, caption=report_text, reply_markup=back_admin_menu_button())


async def stats_month_entered(message: types.Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    try:
        month = int(text)
    except ValueError:
        await message.answer("Неверный номер месяца. Введите число от 1 до 12.")
        return

    if month < 1 or month > 12:
        await message.answer("Неверный номер месяца. Введите число от 1 до 12.")
        return

    today = datetime.date.today()
    year = today.year
    start_date = datetime.date(year, month, 1)
    if month == 12:
        end_date = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        end_date = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    summary = await payments_summary_for_range(start_date, end_date)
    daily = await payments_daily_breakdown(start_date, end_date)
    daily_map = {row[0]: row for row in daily}
    dates = [
        start_date + datetime.timedelta(days=i)
        for i in range((end_date - start_date).days + 1)
    ]
    amounts = [daily_map.get(d, (d, 0, 0, 0, 0))[2] for d in dates]

    unpaid_total = summary["billed_total"] - summary["earned_total"]
    report_text = (
        f"Статистика за {year}-{month:02d}:\n"
        f"Занятий проведено: {summary['lessons_total']}\n"
        f"Оплачено: {summary['lessons_paid']}\n"
        f"Заработано: {summary['earned_total']} ₽\n"
        f"К оплате: {unpaid_total} ₽"
    )

    chart_title = f"Month {year}-{month:02d}"
    chart_buf = build_weekly_report_chart(dates, amounts, title=chart_title)
    chart_file = BufferedInputFile(chart_buf.getvalue(), filename="month.png")
    await state.clear()
    await message.answer_photo(chart_file, caption=report_text, reply_markup=back_admin_menu_button())
