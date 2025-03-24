#!/bin/bash
echo "=== 从倒数第二个目录入口到日志结尾 ==="

tac "$LOG_FILE" | awk '
    /Entering directory/ { 
        entry_count++
        if (entry_count == 2) { 
            print "----- 倒数第二个目录入口 -----"
            print $0
            print "============================="
            buffer = $0 "\n" buffer
            next
        }
    }
    { 
        buffer = $0 "\n" buffer 
    }
    END { 
        print buffer 
    }
' | tac
