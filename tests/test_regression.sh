#!/bin/bash
set -e

echo "=== Keeper Summary 回归测试 ==="
echo ""

# 测试1：基础keeper archive生成
echo "测试1：生成keeper archive（heuristic模式）"
python3 test_keeper_summary.py http-10turn-audit-001 --timeout 10 > /tmp/test1.log 2>&1
if [ $? -eq 0 ]; then
    echo "  ✅ 通过"
else
    echo "  ❌ 失败"
    cat /tmp/test1.log
    exit 1
fi

# 测试2：验证records内容
echo ""
echo "测试2：验证records内容"
python3 << 'PYEOF'
import sys
sys.path.insert(0, 'backend')
from keeper_archive import load_keeper_record_archive

session = 'http-10turn-audit-001'
archive = load_keeper_record_archive(session)
records = archive.get('records', [])

assert len(records) > 0, "records不能为空"
assert len(records) == 2, f"期望2条records，实际{len(records)}条"

for idx, record in enumerate(records):
    assert 'window' in record, f"record {idx} 缺少window字段"
    assert 'stable_entities' in record, f"record {idx} 缺少stable_entities"
    assert len(record.get('stable_entities', [])) >= 1, f"record {idx} 实体数量不足"

print("  ✅ 通过")
PYEOF

# 测试3：验证summary生成
echo ""
echo "测试3：验证summary生成"
python3 << 'PYEOF'
import sys
sys.path.insert(0, 'backend')
from summary_updater import update_summary

session = 'http-10turn-audit-001'
summary = update_summary(session)

assert len(summary) > 100, f"Summary太短：{len(summary)}字符"
assert '# Summary' in summary, "Summary格式不正确"
assert '当前状态锚点' in summary, "Summary缺少关键section"

print("  ✅ 通过")
PYEOF

echo ""
echo "=== 所有测试通过！ ==="
