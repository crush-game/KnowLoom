from app.knowloom.services.markdown_units import parse_units


def test_parser_keeps_regulation_articles_and_exact_ranges() -> None:
    text = "第一章 总则\n第十二条 申请前应完成规定课程。\n（一）提交材料。\n第十三条 本办法自发布之日起施行。\n"
    units = parse_units(text)
    articles = [unit for unit in units if unit.kind == "article"]
    assert len(articles) == 2
    assert articles[0].heading_path[-1] == "第十二条"
    assert articles[0].text == text[articles[0].char_start:articles[0].char_end]
    assert "（一）提交材料" in articles[0].text
