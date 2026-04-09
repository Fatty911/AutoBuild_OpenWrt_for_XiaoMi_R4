import re
text = 'self.__next_f.push([1,"\\"slug\\":\\"qwen-3.6-plus\\""])'
matches = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', text)
print(matches)
