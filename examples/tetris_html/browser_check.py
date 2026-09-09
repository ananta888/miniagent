"""Optional real-browser smoke test; requires Playwright and a local Chromium binary."""
import argparse
import json
from pathlib import Path


def main():
    from playwright.sync_api import sync_playwright
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('html',type=Path)
    cli.add_argument('--chromium',type=Path)
    cli.add_argument('--screenshot',type=Path)
    args=cli.parse_args()
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,executable_path=str(args.chromium) if args.chromium else None)
        page=browser.new_page(viewport={'width':960,'height':800})
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(args.html.resolve().as_uri())
        page.wait_for_function('window.game && window.game.y >= 2',timeout=5000)
        page.evaluate('game.piece=[[1]];game.x=4;game.y=2')
        page.keyboard.press('ArrowLeft')
        assert page.evaluate('game.x')==3
        page.keyboard.press('ArrowRight')
        assert page.evaluate('game.x')==4
        page.evaluate('game.piece=[[0,1,0],[1,1,1],[0,0,0]];game.x=3;game.y=3')
        before=page.evaluate('JSON.stringify(game.piece)')
        page.keyboard.press('ArrowUp')
        assert page.evaluate('JSON.stringify(game.piece)')!=before
        page.evaluate('game.reset();game.piece=[[1,1],[1,1]];game.x=4;game.y=0')
        page.keyboard.press('Space')
        assert page.evaluate('game.board.flat().filter(Boolean).length')==4
        page.evaluate('game.reset();game.board[19]=Array(10).fill(2);game.board[19][4]=0;game.piece=[[1]];game.x=4;game.y=0')
        page.keyboard.press('Space')
        assert page.evaluate('game.score')==100
        assert '100' in page.locator('#score').inner_text()
        page.evaluate('for(let y=0;y<6;y++)game.board[y]=Array(10).fill(2);game.spawn()')
        page.wait_for_function('/over|vorbei/i.test(document.getElementById("status").textContent)')
        page.locator('#restart').click()
        assert page.evaluate('!game.gameOver && game.score===0 && game.board.flat().every(v=>v===0)')
        page.wait_for_function('game.y>=2',timeout=5000)
        if args.screenshot:
            page.screenshot(path=str(args.screenshot))
        assert not errors,errors
        print(json.dumps({'browser_smoke':'passed','checks':['gravity','left/right','rotation','hard_drop',
                         'line_clear','score','game_over','restart','gravity_after_restart'],
                          'page_errors':errors,'browser':browser.version},indent=2))
        browser.close()


if __name__=='__main__':
    main()
