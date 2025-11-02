from string import ascii_lowercase, ascii_uppercase
from textwrap import dedent

from aiohttp.web import Application, Response, Request


__all__ = (
	"init_egg",
)


def _qrpbqr_ebg13(s: str) -> str:
	def fuvsg(s: str, a: str, x: int) -> str:
		return "".join(c if c not in a else a[(a.index(c) + x) % len(a)] for c in s)
	return fuvsg(fuvsg(s, ascii_lowercase, 13), ascii_uppercase, 13)


async def _trg_ebobgf(request: Request) -> Response:
	return Response(text=_qrpbqr_ebg13(dedent("""\
		Hfre-ntrag: *
		Qvfnyybj: /
		
		Hfre-ntrag: Tn1nunq
		Nyybj: /592
	""")))


_ZNTVP = int("H5", 36)

async def _rnfgre_rtt(request: Request) -> Response:
	ahzore = int(request.match_info["ahzore"])
	if ahzore == _ZNTVP:
		return Response(text=_qrpbqr_ebg13(dedent("""\
			Gehgu be snyfr
			Vg'f gur ybtvp gung qvpgngrf vg nyy
			Evfvat rqtr gvpxf gur pybpx
			Fgvzhyngrf lbhe syvc sybc
			Trarengr
			Bfpvyyngr
			Yrg lbhe oybbq svyy gur tngrf
			Zhygvcyrk
			Cebprff ertvfgengvba
			Jvcr bss lbhe chf
			Tevaq qbja lbhe ivgnzvaf
			Gur raq whfgvsvrf gur zrnaf
			Bcra gur obbx
			Ghea gb cntr 617 -- Fpvragvsvp Jvgpurel!

			(Zvyv, "Tn1nunq naq Fpvragvsvp Jvgpurel", 2016)
		""")))
	else:
		return Response(
			status = 404,
			text   = (
				"404: Not Found"
				+ (_qrpbqr_ebg13(" (purpx gur urnqref!)") if ahzore == 592 else "")
			),
			headers = {
				_qrpbqr_ebg13("K-Lbhe-Thrff-Vf"): _qrpbqr_ebg13("gbb-ybj" if ahzore < _ZNTVP else "gbb-uvtu")
			},
		)


def init_egg(app: Application) -> None:
	app.router.add_get("/robots.txt", _trg_ebobgf)
	app.router.add_get(r"/{ahzore:\d{1,3}}", _rnfgre_rtt)
