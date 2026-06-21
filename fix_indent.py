import re

with open("bot1.py", "r") as f:
    lines = f.readlines()

out = []
in_while = False
while_idx = -1
for i, line in enumerate(lines):
    if line.startswith("    while True:") and "DAILY_INTERVAL" in lines[i-1]:
        out.append(line)
        out.append("        try:\n")
        in_while = True
        continue
    
    if in_while:
        if line.startswith("        # Sleep 10 seconds then re-check"):
            # End of the loop content
            out.append("    " + line)
            # Next line is await asyncio.sleep(10)
        elif line.startswith("        await asyncio.sleep(10)"):
            out.append("    " + line)
            # Add except block
            out.append("        except Exception as e:\n")
            out.append("            logging.critical(f\"🔥 [CRITICAL] Fatal error in scheduler loop: {e}\")\n")
            out.append("            traceback.print_exc()\n")
            out.append("            await asyncio.sleep(60)\n")
            in_while = False
        else:
            if line.strip() == "":
                out.append(line)
            else:
                out.append("    " + line)
    else:
        out.append(line)

with open("bot1.py", "w") as f:
    f.writelines(out)
