# 分钟线数据导入 - PowerShell 启动脚本

$PROJECT_ROOT = "E:\project\getrich"
$HDB_PATH = "E:\BaiduNetdiskDownload\data\bar\bar\min_bar"

# 配置
$CONFIG = @{
    host = 'localhost'
    port = 8123
    database = 'default'
    user = 'default'
    password = 'getrich'
    table_name = 'min_bar'
}

function Show-Menu {
    Clear-Host
    Write-Host "========================================"  -ForegroundColor Cyan
    Write-Host "   GetRich 分钟线数据导入工具"  -ForegroundColor Cyan
    Write-Host "========================================"  -ForegroundColor Cyan
    Write-Host ""
    Write-Host "[1] 全量导入 (2005-2025年)"  -ForegroundColor Green
    Write-Host "[2] 增量导入 (自动更新)"  -ForegroundColor Green
    Write-Host "[3] 导入指定年份"  -ForegroundColor Green
    Write-Host "[4] 查看数据库状态"  -ForegroundColor Yellow
    Write-Host "[5] 测试导入功能"  -ForegroundColor Yellow
    Write-Host "[0] 退出"  -ForegroundColor Red
    Write-Host ""
}

function Run-FullImport {
    Write-Host ""
    Write-Host "========================================"  -ForegroundColor Cyan
    Write-Host "开始全量导入..."  -ForegroundColor Cyan
    Write-Host "========================================"  -ForegroundColor Cyan
    Write-Host ""
    
    Set-Location $PROJECT_ROOT
    python -m Data.clickhouse.jobs.daily_import
    
    Write-Host ""
    Write-Host "导入完成！" -ForegroundColor Green
    Read-Host "按任意键继续"
}

function Run-IncrementalImport {
    Write-Host ""
    Write-Host "========================================"  -ForegroundColor Cyan
    Write-Host "开始增量导入..."  -ForegroundColor Cyan
    Write-Host "========================================"  -ForegroundColor Cyan
    Write-Host ""
    
    Set-Location $PROJECT_ROOT
    
    $code = @"
from Data.clickhouse.jobs.daily_import import MinBarImportJob
from lntools import Logger

logger = Logger('main')
importer = MinBarImportJob(
    hdb_base_path=r'$HDB_PATH',
    clickhouse_config=$($CONFIG | ConvertTo-Json -Compress),
    max_workers=4
)
importer.run_incremental_import()
importer.close()
"@
    
    python -c $code
    
    Write-Host ""
    Write-Host "增量导入完成！" -ForegroundColor Green
    Read-Host "按任意键继续"
}

function Run-YearImport {
    Write-Host ""
    $startYear = Read-Host "请输入开始年份 (如 2005)"
    $endYear = Read-Host "请输入结束年份 (如 2010)"
    
    Write-Host ""
    Write-Host "========================================"  -ForegroundColor Cyan
    Write-Host "导入 $startYear - $endYear 年数据..."  -ForegroundColor Cyan
    Write-Host "========================================"  -ForegroundColor Cyan
    Write-Host ""
    
    Set-Location $PROJECT_ROOT
    
    $code = @"
from Data.clickhouse.jobs.daily_import import MinBarImportJob

importer = MinBarImportJob(
    hdb_base_path=r'$HDB_PATH',
    clickhouse_config=$($CONFIG | ConvertTo-Json -Compress),
    max_workers=4
)
importer.run_full_import(
    start_year=$startYear,
    end_year=$endYear,
    skip_existing=True
)
importer.close()
"@
    
    python -c $code
    
    Write-Host ""
    Write-Host "导入完成！" -ForegroundColor Green
    Read-Host "按任意键继续"
}

function Check-Status {
    Write-Host ""
    Write-Host "========================================"  -ForegroundColor Cyan
    Write-Host "查询数据库状态..."  -ForegroundColor Cyan
    Write-Host "========================================"  -ForegroundColor Cyan
    Write-Host ""
    
    Set-Location $PROJECT_ROOT
    python -m Data.clickhouse.jobs.test_import latest
    
    Write-Host ""
    Read-Host "按任意键继续"
}

function Test-Import {
    Write-Host ""
    Write-Host "========================================"  -ForegroundColor Cyan
    Write-Host "测试导入功能"  -ForegroundColor Cyan
    Write-Host "========================================"  -ForegroundColor Cyan
    Write-Host ""
    Write-Host "[1] 测试获取最新日期"
    Write-Host "[2] 测试导入单个日期"
    Write-Host "[3] 测试导入一年数据"
    Write-Host "[4] 测试增量导入"
    Write-Host ""
    
    $testChoice = Read-Host "请选择测试项 (1-4)"
    
    Set-Location $PROJECT_ROOT
    
    switch ($testChoice) {
        "1" { python -m Data.clickhouse.jobs.test_import latest }
        "2" { python -m Data.clickhouse.jobs.test_import single }
        "3" { python -m Data.clickhouse.jobs.test_import year }
        "4" { python -m Data.clickhouse.jobs.test_import incremental }
        default { Write-Host "无效选项" -ForegroundColor Red }
    }
    
    Write-Host ""
    Read-Host "按任意键继续"
}

# 主循环
do {
    Show-Menu
    $choice = Read-Host "请输入选项 (0-5)"
    
    switch ($choice) {
        "1" { Run-FullImport }
        "2" { Run-IncrementalImport }
        "3" { Run-YearImport }
        "4" { Check-Status }
        "5" { Test-Import }
        "0" { 
            Write-Host ""
            Write-Host "程序已退出" -ForegroundColor Yellow
            break 
        }
        default {
            Write-Host ""
            Write-Host "无效选项，请重新选择" -ForegroundColor Red
            Start-Sleep -Seconds 2
        }
    }
} while ($choice -ne "0")
