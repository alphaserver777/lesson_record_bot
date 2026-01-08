"""Генерация графических отчетов."""
import io
import datetime

from PIL import Image, ImageDraw, ImageFont


def build_weekly_report_chart(
    dates: list[datetime.date],
    amounts: list[int],
    title: str | None = None,
) -> io.BytesIO:
    """
    Рисует простой бар-чарт по сумме выручки за дни недели.
    Возвращает BytesIO с PNG.
    """
    width, height = 900, 480
    margin = 60
    bg_color = (255, 255, 255)
    axis_color = (40, 40, 40)
    bar_color = (46, 125, 240)
    text_color = (20, 20, 20)

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default()

    # Оси
    draw.line((margin, height - margin, width - margin, height - margin), fill=axis_color, width=2)
    draw.line((margin, margin, margin, height - margin), fill=axis_color, width=2)

    if title:
        draw.text((margin, 15), title, font=font, fill=text_color)

    if not dates:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return buf

    max_val = max(amounts) if amounts else 0
    if max_val <= 0:
        max_val = 1

    bar_area_w = width - 2 * margin
    bar_area_h = height - 2 * margin
    group_w = bar_area_w / len(dates)
    bar_w = max(12, int(group_w * 0.6))

    total_days = len(dates)
    label_step = 1 if total_days <= 10 else 2 if total_days <= 20 else 3

    for i, (day, value) in enumerate(zip(dates, amounts)):
        x_center = margin + i * group_w + group_w / 2
        x0 = int(x_center - bar_w / 2)
        x1 = int(x_center + bar_w / 2)
        bar_h = int(bar_area_h * (value / max_val))
        y1 = height - margin
        y0 = y1 - bar_h
        draw.rectangle((x0, y0, x1, y1), fill=bar_color)

        if i % label_step == 0:
            label = str(day.day)
            label_w = draw.textlength(label, font=font)
            draw.text((x_center - label_w / 2, height - margin + 6), label, font=font, fill=text_color)

        val_text = str(value)
        val_w = draw.textlength(val_text, font=font)
        draw.text((x_center - val_w / 2, y0 - 14), val_text, font=font, fill=text_color)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf
