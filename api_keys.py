import logging
from typing import Optional, Dict, Any, List

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from models.api_keys import Api_keys

logger = logging.getLogger(__name__)


# ------------------ Service Layer ------------------
class Api_keysService:
    """Service layer for Api_keys operations"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: Dict[str, Any], user_id: Optional[str] = None) -> Optional[Api_keys]:
        """Create a new api_keys"""
        try:
            if user_id:
                data['user_id'] = user_id
            obj = Api_keys(**data)
            self.db.add(obj)
            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Created api_keys with id: {obj.id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error creating api_keys: {str(e)}")
            raise

    async def check_ownership(self, obj_id: int, user_id: str) -> bool:
        """Check if user owns this record"""
        try:
            obj = await self.get_by_id(obj_id, user_id=user_id)
            return obj is not None
        except Exception as e:
            logger.error(f"Error checking ownership for api_keys {obj_id}: {str(e)}")
            return False

    async def get_by_id(self, obj_id: int, user_id: Optional[str] = None) -> Optional[Api_keys]:
        """Get api_keys by ID (user can only see their own records)"""
        try:
            query = select(Api_keys).where(Api_keys.id == obj_id)
            if user_id:
                query = query.where(Api_keys.user_id == user_id)
            result = await self.db.execute(query)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching api_keys {obj_id}: {str(e)}")
            raise

    async def get_list(
        self, 
        skip: int = 0, 
        limit: int = 20, 
        user_id: Optional[str] = None,
        query_dict: Optional[Dict[str, Any]] = None,
        sort: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get paginated list of api_keyss (user can only see their own records)"""
        try:
            query = select(Api_keys)
            count_query = select(func.count(Api_keys.id))
            
            if user_id:
                query = query.where(Api_keys.user_id == user_id)
                count_query = count_query.where(Api_keys.user_id == user_id)
            
            if query_dict:
                for field, value in query_dict.items():
                    if hasattr(Api_keys, field):
                        query = query.where(getattr(Api_keys, field) == value)
                        count_query = count_query.where(getattr(Api_keys, field) == value)
            
            count_result = await self.db.execute(count_query)
            total = count_result.scalar()

            if sort:
                if sort.startswith('-'):
                    field_name = sort[1:]
                    if hasattr(Api_keys, field_name):
                        query = query.order_by(getattr(Api_keys, field_name).desc())
                else:
                    if hasattr(Api_keys, sort):
                        query = query.order_by(getattr(Api_keys, sort))
            else:
                query = query.order_by(Api_keys.id.desc())

            result = await self.db.execute(query.offset(skip).limit(limit))
            items = result.scalars().all()

            return {
                "items": items,
                "total": total,
                "skip": skip,
                "limit": limit,
            }
        except Exception as e:
            logger.error(f"Error fetching api_keys list: {str(e)}")
            raise

    async def update(self, obj_id: int, update_data: Dict[str, Any], user_id: Optional[str] = None) -> Optional[Api_keys]:
        """Update api_keys (requires ownership)"""
        try:
            obj = await self.get_by_id(obj_id, user_id=user_id)
            if not obj:
                logger.warning(f"Api_keys {obj_id} not found for update")
                return None
            for key, value in update_data.items():
                if hasattr(obj, key) and key != 'user_id':
                    setattr(obj, key, value)

            await self.db.commit()
            await self.db.refresh(obj)
            logger.info(f"Updated api_keys {obj_id}")
            return obj
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error updating api_keys {obj_id}: {str(e)}")
            raise

    async def delete(self, obj_id: int, user_id: Optional[str] = None) -> bool:
        """Delete api_keys (requires ownership)"""
        try:
            obj = await self.get_by_id(obj_id, user_id=user_id)
            if not obj:
                logger.warning(f"Api_keys {obj_id} not found for deletion")
                return False
            await self.db.delete(obj)
            await self.db.commit()
            logger.info(f"Deleted api_keys {obj_id}")
            return True
        except Exception as e:
            await self.db.rollback()
            logger.error(f"Error deleting api_keys {obj_id}: {str(e)}")
            raise

    async def get_by_field(self, field_name: str, field_value: Any) -> Optional[Api_keys]:
        """Get api_keys by any field"""
        try:
            if not hasattr(Api_keys, field_name):
                raise ValueError(f"Field {field_name} does not exist on Api_keys")
            result = await self.db.execute(
                select(Api_keys).where(getattr(Api_keys, field_name) == field_value)
            )
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching api_keys by {field_name}: {str(e)}")
            raise

    async def list_by_field(
        self, field_name: str, field_value: Any, skip: int = 0, limit: int = 20
    ) -> List[Api_keys]:
        """Get list of api_keyss filtered by field"""
        try:
            if not hasattr(Api_keys, field_name):
                raise ValueError(f"Field {field_name} does not exist on Api_keys")
            result = await self.db.execute(
                select(Api_keys)
                .where(getattr(Api_keys, field_name) == field_value)
                .offset(skip)
                .limit(limit)
                .order_by(Api_keys.id.desc())
            )
            return result.scalars().all()
        except Exception as e:
            logger.error(f"Error fetching api_keyss by {field_name}: {str(e)}")
            raise