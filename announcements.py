import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.announcements import Announcements

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class AnnouncementsService:
    """Service layer for Announcements operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any]) -> Optional[Announcements]:
        """Create a new announcements"""
        try:
            obj = Announcements(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Created announcements with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating announcements: {str(e)}")
            raise

    async def get_by_id(self, obj_id: int) -> Optional[Announcements]:
        """Get announcements by ID"""
        try:
            query = select(Announcements).where(Announcements.id == obj_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching announcements {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of announcementss"""
        try:
            query = select(Announcements)
            count_query = select(func.count(Announcements.id))
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Announcements, field):
                        query = query.where(getattr(Announcements, field) == value)
                        count_query = count_query.where(getattr(Announcements, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Announcements, field_name):
                        query = query.order_by(getattr(Announcements, field_name).desc())
                else:
                    if hasattr(Announcements, sort):
                        query = query.order_by(getattr(Announcements, sort))
            else:
                query = query.order_by(Announcements.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching announcements list: {str(e)}")
            raise

    async def update(self, obj_id: int, update_data: Dict[str, Any]) -> Optional[Announcements]:
        """Update announcements"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Announcements {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Updated announcements {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating announcements {obj_id}: {str(e)}")
            raise

    async def delete(self, obj_id: int) -> bool:
        """Delete announcements"""
        try:
            obj = await self.get_by_id(obj_id)
            if not obj:
                logger.warning(f"Announcements {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted announcements {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting announcements {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Announcements]:
        """Get announcements by any field"""
        try:
            if not hasattr(Announcements, field_name):
                raise ValueError(f"Field {field_name} does not exist on Announcements")
            result = await self.db.execute(
                select(Announcements).where(getattr(Announcements, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching announcements by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Announcements]:
        """Get list of announcementss filtered by field"""
        try:
            if not hasattr(Announcements, field_name):
                raise ValueError(f"Field {field_name} does not exist on Announcements")
            result = await self.db.execute(
                select(Announcements)
                .where(getattr(Announcements, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Announcements.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching announcementss by {field_name}: {str(e)}")
            raise