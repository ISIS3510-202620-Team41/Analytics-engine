"""Pruebas de BQ11: cupones comerciales durante los descansos entre clases.

Lo que de verdad se protege aqui es la validez de la comparacion. La metrica podria
devolver numeros perfectamente plausibles y estar mal: basta con meter en el grupo de
control a los usuarios de los que no se sabe nada para que la diferencia entre ambos
lados se encoja. Ese sesgo no se ve mirando la respuesta, solo se ve probandolo.
"""
import unittest
from datetime import timedelta

from db import connect
from filters import Filters
from metrics.deal_break_funnel import deal_break_funnel
from tests.helpers import NOW, U1, U2, U3, DbTestCase, row


class DealBreakFunnelTests(DbTestCase):

    def _run(self):
        with connect() as conn:
            return deal_break_funnel(conn, Filters(to=NOW + timedelta(seconds=1)))

    def test_compara_las_dos_tasas_de_redencion(self):
        self.load([
            # En descanso: 10 impresiones, 4 aperturas, 2 redenciones.
            row("deals_shown", user=U1, deal_count=10, during_break=1),
            row("deal_opened", user=U1, deal_id="d1", deal_category="CAFE", during_break=1),
            row("deal_opened", user=U1, deal_id="d2", deal_category="CAFE", during_break=1),
            row("deal_opened", user=U1, deal_id="d3", deal_category="COMIDA", during_break=1),
            row("deal_opened", user=U2, deal_id="d1", deal_category="CAFE", during_break=1),
            row("deal_redeemed", user=U1, deal_id="d1", deal_category="CAFE", during_break=1),
            row("deal_redeemed", user=U2, deal_id="d1", deal_category="CAFE", during_break=1),

            # Fuera de descanso: 20 impresiones, 2 aperturas, 1 redencion.
            row("deals_shown", user=U2, deal_count=20, during_break=0),
            row("deal_opened", user=U2, deal_id="d4", deal_category="CINE", during_break=0),
            row("deal_opened", user=U3, deal_id="d4", deal_category="CINE", during_break=0),
            row("deal_redeemed", user=U3, deal_id="d4", deal_category="CINE", during_break=0),
        ])

        result = self._run()

        self.assertEqual(result["duringBreak"]["shown"], 10)
        self.assertEqual(result["duringBreak"]["opened"], 4)
        self.assertEqual(result["duringBreak"]["redeemed"], 2)
        self.assertAlmostEqual(result["duringBreak"]["redemptionRate"], 0.2)

        self.assertEqual(result["outsideBreak"]["shown"], 20)
        self.assertAlmostEqual(result["outsideBreak"]["redemptionRate"], 0.05)

        # La respuesta de una sola cifra: durante los descansos se redime 4 veces mas.
        self.assertAlmostEqual(result["redemptionLift"], 4.0)

    def test_los_eventos_sin_horario_no_entran_en_la_comparacion(self):
        """El test que sostiene la validez de toda la BQ.

        Si los NULL se contaran como "fuera de descanso", las 100 impresiones de abajo
        inflarian el denominador del grupo de control y su tasa caeria a casi cero: la
        BQ reportaria una mejora enorme que no existe.
        """
        self.load([
            row("deals_shown", user=U1, deal_count=10, during_break=1),
            row("deal_redeemed", user=U1, deal_id="d1", during_break=1),

            row("deals_shown", user=U2, deal_count=10, during_break=0),
            row("deal_redeemed", user=U2, deal_id="d2", during_break=0),

            # Usuario sin horario importado: no se sabe en que momento del dia estaba.
            row("deals_shown", user=U3, deal_count=100, during_break=None),
            row("deal_opened", user=U3, deal_id="d3", during_break=None),
        ])

        result = self._run()

        # Las dos tasas son identicas y el multiplicador es 1: los 100 desconocidos no
        # tocaron ninguno de los dos lados.
        self.assertEqual(result["duringBreak"]["shown"], 10)
        self.assertEqual(result["outsideBreak"]["shown"], 10)
        self.assertAlmostEqual(result["redemptionLift"], 1.0)

        # Pero no se esconden: se reportan para que quien lea la respuesta sepa sobre
        # cuanta poblacion se calculo.
        self.assertEqual(result["eventsWithUnknownContext"], 2)

    def test_las_impresiones_se_suman_y_no_se_cuentan(self):
        """Un evento de impresion representa una pantalla con varias tarjetas.

        Contar los eventos en vez de sumar su `deal_count` daria un denominador diez
        veces menor y las tasas saldrian infladas en la misma proporcion.
        """
        self.load([
            row("deals_shown", user=U1, deal_count=7, during_break=1),
            row("deals_shown", user=U1, deal_count=5, during_break=1),
            row("deal_redeemed", user=U1, deal_id="d1", during_break=1),
        ])

        result = self._run()

        self.assertEqual(result["duringBreak"]["shown"], 12)   # 7 + 5, no 2
        self.assertAlmostEqual(result["duringBreak"]["redemptionRate"], 1 / 12)

    def test_sin_datos_no_se_divide_entre_cero(self):
        result = self._run()

        self.assertEqual(result["duringBreak"]["shown"], 0)
        self.assertEqual(result["duringBreak"]["redemptionRate"], 0.0)
        # None y no 0: "no se puede calcular el multiplicador" no es "no hay diferencia".
        self.assertIsNone(result["redemptionLift"])

    def test_el_desglose_por_categoria_es_solo_de_los_descansos(self):
        self.load([
            row("deal_opened", user=U1, deal_id="d1", deal_category="CAFE", during_break=1),
            row("deal_opened", user=U2, deal_id="d2", deal_category="CAFE", during_break=1),
            row("deal_redeemed", user=U1, deal_id="d1", deal_category="CAFE", during_break=1),
            # Fuera del descanso: no debe aparecer en el desglose.
            row("deal_opened", user=U3, deal_id="d3", deal_category="GIMNASIO", during_break=0),
            row("deal_redeemed", user=U3, deal_id="d3", deal_category="GIMNASIO", during_break=0),
        ])

        categories = {c["category"]: c for c in self._run()["byCategoryDuringBreak"]}

        self.assertIn("CAFE", categories)
        self.assertNotIn("GIMNASIO", categories)
        self.assertEqual(categories["CAFE"]["opened"], 2)
        self.assertEqual(categories["CAFE"]["redeemed"], 1)
        self.assertAlmostEqual(categories["CAFE"]["redemptionRatePerOpen"], 0.5)

    def test_los_eventos_fuera_del_periodo_no_cuentan(self):
        self.load([
            row("deals_shown", user=U1, deal_count=10, during_break=1, at=NOW - timedelta(days=40)),
            row("deal_redeemed", user=U1, deal_id="d1", during_break=1, at=NOW - timedelta(days=40)),
            row("deals_shown", user=U1, deal_count=10, during_break=1),
        ])

        with connect() as conn:
            result = deal_break_funnel(
                conn,
                Filters(from_=NOW - timedelta(days=7), to=NOW + timedelta(seconds=1))
            )

        self.assertEqual(result["duringBreak"]["shown"], 10)
        self.assertEqual(result["duringBreak"]["redeemed"], 0)


if __name__ == "__main__":
    unittest.main()
