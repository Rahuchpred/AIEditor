import re

with open('app/api/reel_routes.py', 'r') as f:
    content = f.read()

# Replace button classes
content = content.replace('class="ghost"', 'class="btn-ghost"')
content = content.replace('class="ghost ', 'class="btn-ghost ')
content = content.replace('chooseBtn.className = item.id === currentSelectedHookId ? "ghost" : "";', 'chooseBtn.className = item.id === currentSelectedHookId ? "btn-ghost" : "btn-primary";')

with open('app/api/reel_routes.py', 'w') as f:
    f.write(content)
print("Updated JS text content")
