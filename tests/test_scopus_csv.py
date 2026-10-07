"""Tests for Scopus CSV parsing."""

import tempfile
from pathlib import Path
from citation_tracker.scopus.csv_parser import parse_scopus_csv


def test_parse_scopus_csv():
    csv_content = """Authors,Title,Year,Source title,Volume,Issue,Art. No.,Page start,Page end,Page count,Cited by,DOI,Link,Affiliations,Authors with affiliations,Abstract,Author Keywords,Index Keywords,EID
"Rossi M., Bianchi L.","Deep Learning in Medical Imaging",2021,"Medical Image Analysis",10,2,,100,115,16,14,"10.1016/j.media.2021.100","https://www.scopus.com/record/display.uri?eid=2-s2.0-85099999999","Univ","Univ","Abstract text","DL; Medical",,"2-s2.0-85099999999"
"Rossi M.","Graph Neural Networks Overview",2020,"IEEE Transactions on NN",5,,,50,60,11,8,"10.1109/TNN.2020.50","https://www.scopus.com/record/display.uri?eid=2-s2.0-85088888888","Univ","Univ","Abstract 2","GNN",,"2-s2.0-85088888888"
"""
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as f:
        f.write(csv_content)
        temp_path = Path(f.name)

    try:
        papers = parse_scopus_csv(temp_path)
        assert len(papers) == 2
        assert papers[0].title == "Deep Learning in Medical Imaging"
        assert papers[0].year == 2021
        assert papers[0].eid == "2-s2.0-85099999999"
        assert papers[0].doi == "10.1016/j.media.2021.100"
        assert papers[0].cited_by_count == 14
        assert papers[1].title == "Graph Neural Networks Overview"
        assert papers[1].year == 2020
    finally:
        temp_path.unlink()

