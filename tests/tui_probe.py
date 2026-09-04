"""把 TUI 畫面抓成純文字，供測試斷言與人工檢視。"""


def screen_text(app) -> str:
    return "\n".join(
        "".join(segment.text for segment in strip)
        for strip in app.screen._compositor.render_strips()
    )


def screen_colours(app) -> list[tuple[str, str | None]]:
    """畫面上每一段文字與它的前景色。

    顏色沒有掉光要看得出來——文字相同、顏色不同，只有渲染成畫面才分得出來。
    """
    return [
        (
            segment.text,
            None if segment.style is None or segment.style.color is None else segment.style.color.name,
        )
        for strip in app.screen._compositor.render_strips()
        for segment in strip
    ]


def colour_of(app, text: str) -> str | None:
    """畫面上第一段等於 text 的那一小段是什麼顏色。"""
    for shown, colour in screen_colours(app):
        if shown == text:
            return colour
    return None
