import re

with open('app/api/routes.py', 'r') as f:
    content = f.read()

# Replace button text updates
content = content.replace('.textContent = "Play";', '.textContent = "Play";')
content = content.replace('.textContent = "Pause";', '.textContent = "Pause";')
content = content.replace('id="autoCutBtn"', 'id="autoCutBtn"')
content = content.replace('id="renderEditorBtn"', 'id="renderEditorBtn"')
content = content.replace('id="exportSrtBtn"', 'id="exportSrtBtn"')
content = content.replace('class="ghost"', 'class="btn-ghost"')
content = content.replace('class="ghost ', 'class="btn-ghost ')
content = content.replace('id="statusBtn" class="ghost"', 'id="statusBtn" class="btn-ghost"')
content = content.replace('id="resultBtn" class="ghost"', 'id="resultBtn" class="btn-ghost"')

# Actually, the python script I already ran replaced all the HTML but I need to make sure the JS didn't break. 
# Did I change IDs?
# old: <button id="playPauseBtn" type="button">Play</button>
# new: <button id="playPauseBtn" class="btn-ghost" type="button">Play</button>

# old: <button id="autoCutBtn" class="ghost" type="button" disabled>Open Caption Editor</button>
# new: <button id="autoCutBtn" class="btn-ghost" type="button" disabled>Open Editor</button>
content = content.replace('autoCutBtn.textContent = "Open Caption Editor";', 'autoCutBtn.textContent = "Open Editor";')

with open('app/api/routes.py', 'w') as f:
    f.write(content)
print("Updated JS text content")
