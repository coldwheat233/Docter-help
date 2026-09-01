"""上游数据源（mock）。

v2：模拟医院 HIS 系统、医生自助端、运维录入对排班的修改。
所有变更先入 `upstream_changes` 表，Agent 落库前 re-check。
"""
