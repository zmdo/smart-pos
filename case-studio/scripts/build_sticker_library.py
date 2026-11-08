"""Explicit maintainer bootstrap: bundled Twemoji PNGs and Qwen standard avatars."""
import argparse, concurrent.futures, json, sys
from pathlib import Path
import httpx, cairosvg
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio import avatar_api
from studio.common import read, save, sha

FACE_NAMES = "开心 笑眼 笑哭 大笑 笑眯眯 尴尬笑 笑开花 天使 小恶魔 眨眼 温柔微笑 馋嘴 释然 爱心眼 墨镜 得意 平静 无语 不悦 汗颜 沉思 疑惑 困扰 亲亲 飞吻 甜蜜亲吻 闭眼亲吻 吐舌 眨眼吐舌 眯眼吐舌 失落 担忧 生气 气鼓鼓 流泪 忍耐 哼哼 如释重负 难过 惊慌 害怕 疲惫 困倦 累坏 龇牙 大哭 张嘴 吃惊 紧张 惊叫 惊讶 害羞 睡觉 晕乎 沉默 口罩".split()
# Stable names below use Unicode codepoints as a fallback; tags remain searchable.
OTHER = [
 (0x1f638,"开心猫"),(0x1f639,"笑哭猫"),(0x1f63a,"微笑猫"),(0x1f63b,"心动猫"),(0x1f63c,"得意猫"),(0x1f63d,"亲亲猫"),(0x1f63e,"生气猫"),(0x1f63f,"流泪猫"),(0x1f640,"惊讶猫"),
 (0x1f910,"保密"),(0x1f911,"发财"),(0x1f912,"休息"),(0x1f913,"眼镜"),(0x1f914,"思考"),(0x1f915,"加油康复"),(0x1f916,"机器人"),(0x1f917,"拥抱"),
 (0x1f920,"牛仔"),(0x1f921,"小丑"),(0x1f922,"晕车"),(0x1f923,"笑翻"),(0x1f924,"馋嘴"),(0x1f925,"长鼻子"),
 (0x1f92a,"鬼马"),(0x1f92b,"嘘"),(0x1f92c,"炸毛"),(0x1f92d,"捂嘴笑"),(0x1f92e,"晕乎乎"),(0x1f92f,"大吃一惊"),(0x1f9d0,"单片眼镜"),
 (0x1f436,"小狗"),(0x1f431,"小猫"),(0x1f42d,"小鼠"),(0x1f439,"仓鼠"),(0x1f430,"兔子"),(0x1f43b,"小熊"),(0x1f43c,"熊猫"),(0x1f428,"考拉"),(0x1f42f,"老虎"),(0x1f981,"狮子"),(0x1f98a,"狐狸")]

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--revision',default='b6b55fef1e8636b540a6d016a4729ca8cdf2e60b',help='Pinned jdecked/twemoji commit')
    parser.add_argument('--avatars-only',action='store_true',help='Refresh standard avatars; preserve existing emoji assets')
    args=parser.parse_args(); args.out.mkdir(parents=True,exist_ok=True)
    upstream=f'https://raw.githubusercontent.com/jdecked/twemoji/{args.revision}'
    items=[(code,FACE_NAMES[i] if i<len(FACE_NAMES) else f'表情 {code:x}') for i,code in enumerate(range(0x1f600,0x1f638))]+OTHER
    assert len(items)==97
    def fetch(pair):
        code,name=pair; sid=f'twemoji-{code:x}'
        svg=args.out/(sid+'.svg'); png=args.out/(sid+'.png')
        if not svg.exists():
            with httpx.Client(timeout=30,follow_redirects=True,trust_env=False) as client:
                response=client.get(f'{upstream}/assets/svg/{code:x}.svg');response.raise_for_status()
                svg.write_bytes(response.content)
        if not png.exists(): cairosvg.svg2png(url=str(svg),write_to=str(png),output_width=512,output_height=512)
        category='动物' if code in [v[0] for v in OTHER[-11:]] or 0x1f638<=code<=0x1f640 else '表情'
        return {'id':sid,'name':name,'file':png.name,'gender':'neutral','tags':[category,'通用',name],
                'source':f'https://github.com/jdecked/twemoji/blob/{args.revision}/assets/svg/{code:x}.svg',
                'license':'CC BY 4.0','attribution':'Twemoji graphics by Twitter, Inc and other contributors; SVG rasterized to PNG.', 'sha256':sha(png)}
    previous=read(args.out/'catalog.json',[])
    if args.avatars_only:
        catalog=[s for s in previous if not s['id'].startswith('ai-standard-')]
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool: catalog=list(pool.map(fetch,items))
    # Retain old IDs/files so historical reviews still resolve their exact avatar.
    catalog += [dict(s,retired=True) for s in previous if s['id'].startswith('ai-standard-') and not s['id'].endswith('-expressive-v2')]
    def standard(spec):
        gender,word,name=spec
        sid='ai-standard-'+gender+'-expressive-v2'; target=args.out/(sid+'.png')
        prompt=avatar_api.build_prompt(word,'standard-'+gender)
        if not target.exists():
            image,trace=avatar_api.generate(prompt,nonce=avatar_api.STYLE_VERSION+'-standard-'+gender)
            target.write_bytes(image.read_bytes())
            save(args.out/(sid+'-generation.json'),{'prompt':prompt,'model':trace['model'],'key':trace['key'],'style_version':avatar_api.STYLE_VERSION})
        return {'id':sid,'name':name,'file':target.name,'gender':gender,'tags':['AI头像','3D卡通','透明','装饰','生动表情'],
                'style_version':avatar_api.STYLE_VERSION,'source':'Qwen Image API','license':'API generated','sha256':sha(target)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        catalog += list(pool.map(standard,[('male','男','帅气帽饰男头像'),('female','女','温柔蝴蝶结女头像'),('neutral','','活泼通用头像')]))
    if not (args.out/'LICENSE-TWEMOJI.txt').exists():
        with httpx.Client(timeout=30,trust_env=False) as client:
            response=client.get(upstream+'/LICENSE-GRAPHICS');response.raise_for_status()
            (args.out/'LICENSE-TWEMOJI.txt').write_text(response.text)
    (args.out/'ATTRIBUTION.txt').write_text('Twemoji graphics © Twitter, Inc and other contributors. Licensed under CC BY 4.0: https://creativecommons.org/licenses/by/4.0/\nSource: https://github.com/jdecked/twemoji/tree/'+args.revision+'\nSVG artwork rasterized to 512px PNG; optional opaque privacy backing is added during compositing.\nStandard avatars generated by Qwen Image 2.1 Pro API.\n')
    save(args.out/'catalog.json',catalog)
    print(json.dumps({'count':len(catalog),'output':str(args.out)},ensure_ascii=False))

if __name__=='__main__': main()
