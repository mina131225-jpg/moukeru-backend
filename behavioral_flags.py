import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.behavioral_flags import Behavioral_flags

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class Behavioral_flagsService:
    """Service layer for Behavioral_flags operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any]) -> Optional[Behavioral_flags]:
        """Create a new behavioral_flags"""
        try:
            obj = Behavioral_flags(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Created behavioral_flags with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating behavioral_flags: {str(e)}")
            raise

    async def get_by_id(self, obj_id: int) -> Optional[Behavioral_flags]:
        """Get behavioral_flags by ID"""
        try:
            query = select(Behavioral_flags).where(Behavioral_flags.id == obj_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching behavioral_flags {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of behavioral_flagss"""
        try:
            query = select(Behavioral_flags)
            count_query = select(func.count(Behavioral_flags.id))
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Behavioral_flags, field):
                        query = query.where(getattr(Behavioral_flags, field) == value)
                        count_query = count_query.where(getattr(Behavioral_flags, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Behavioral_flags, field_name):
                        query = query.order_by(getattr(Behavioral_flags, field_name).desc())
                else:
                    if hasattr(Behavioral_flags, sort):
                        query = query.order_by(getattr(Behavioral_flags, sort))
            else:
                query = query.order_by(Behavioral_flags.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching behavioral_flags list: {str(e)}")
            raise

    async def update(self, obj_id: int, update_data: Dict[str, Any]) -> Optional[Behavioral_flags]:
        """Update behavioral_flags"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Behavioral_flags {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Updated behavioral_flags {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating behavioral_flags {obj_id}: {str(e)}")
            raise

    async def delete(self, obj_id: int) -> bool:
        """Delete behavioral_flags"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Behavioral_flags {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted behavioral_flags {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting behavioral_flags {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Behavioral_flags]:
        """Get behavioral_flags by any field"""
        try:
            if not hasattr(Behavioral_flags, field_name):
                raise ValueError(f"Field {field_name} does not exist on Behavioral_flags")
            result = await self.db.execute(
                select(Behavioral_flags).where(getattr(Behavioral_flags, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching behavioral_flags by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Behavioral_flags]:
        """Get list of behavioral_flagss filtered by field"""
        try:
            if not hasattr(Behavioral_flags, field_name):
                raise ValueError(f"Field {field_name} does not exist on Behavioral_flags")
            result = await self.db.execute(
                select(Behavioral_flags)
                .where(getattr(Behavioral_flags, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Behavioral_flags.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching behavioral_flagss by {field_name}: {str(e)}")
            raise