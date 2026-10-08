"""Import every model so SQLAlchemy metadata (and Alembic) see the full schema."""

from weza.domains import misc_models as _misc  # noqa: F401
from weza.domains.appetite import models as _appetite  # noqa: F401
from weza.domains.commercial import models as _commercial  # noqa: F401
from weza.domains.consent import models as _consent  # noqa: F401
from weza.domains.customer import models as _customer  # noqa: F401
from weza.domains.identity import models as _identity  # noqa: F401
from weza.domains.institution import models as _institution  # noqa: F401
from weza.domains.matching import models as _matching  # noqa: F401
from weza.domains.need import models as _need  # noqa: F401
from weza.domains.opportunity import models as _opportunity  # noqa: F401
from weza.domains.product import models as _product  # noqa: F401
from weza.domains.trust import models as _trust  # noqa: F401
from weza.platform import models as _platform  # noqa: F401
from weza.platform.db import Base

metadata = Base.metadata
